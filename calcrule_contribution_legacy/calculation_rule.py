from django.contrib.contenttypes.models import ContentType
from django.db.models.query import Q

from core.abs_calculation_rule import AbsStrategy
from calcrule_contribution_legacy.config import CLASS_RULE_PARAM_VALIDATION, \
    DESCRIPTION_CONTRIBUTION_VALUATION, FROM_TO
from calcrule_contribution_legacy.converters import PolicyToInvoiceConverter, PolicyToLineItemConverter, \
    ContractToInvoiceConverter, ContractCpdToLineItemConverter

from policy.values import (
    sum_contributions,
    sum_general_assemblies,
    sum_registrations,
    family_counts,
    cycle_start
)

from core.models import User
from core.signals import register_service_signal, REGISTERED_SERVICE_SIGNALS
from core import datetime
from policy.models import Policy
import json
from uuid import UUID


class ContributionPlanCalculationRuleProductModeling(AbsStrategy):
    version = 1
    uuid = "2aee6d54-eef4-4ee6-1c47-2793cfa5f9a8"
    calculation_rule_name = "CV: legacy"
    description = DESCRIPTION_CONTRIBUTION_VALUATION
    impacted_class_parameter = CLASS_RULE_PARAM_VALIDATION
    date_valid_from = datetime.datetime(2000, 1, 1)
    date_valid_to = None
    status = "active"
    from_to = FROM_TO
    type = "account_receivable"
    sub_type = "contribution"


    @classmethod
    def active_for_object(cls, instance, context, type="account_receivable", sub_type="contribution"):
        return (
            (
                instance.__class__.__name__ in ["ContributionPlan", "Policy"]
                and context in ["submit", "PolicyCreatedInvoice", "ContractCreated"]
            )
            or (
                instance.__class__.__name__ == "ContractContributionPlanDetails"
                and context in ["value", "members", "validity"]
            )
        ) and cls.check_calculation(instance)

    @classmethod
    def check_calculation(cls, instance):
        match = False
        class_name = instance.__class__.__name__
        list_class_name = [
            "PolicyHolder", "ContributionPlan",
            "PolicyHolderInsuree", "ContractDetails",
            "ContractContributionPlanDetails", "ContributionPlanBundle"
        ]
        if class_name == "ABCMeta":
            match = UUID(str(cls.uuid)) == UUID(str(instance.uuid))
        elif class_name == "ContributionPlan":
            match = UUID(str(cls.uuid)) == UUID(str(instance.calculation))
        elif class_name == "ContributionPlanBundle":
            list_cpbd = list(instance.contributionplanbundledetails_set.filter(
                is_deleted=False
            ))
            for cpbd in list_cpbd:
                if match is False:
                    if cls.check_calculation(cpbd.contribution_plan):
                        match = True
        elif class_name == "Policy":
            match = cls.check_calculation(instance.family)
        # for legacy the calculation is valid for all famillies
        elif class_name == "Family":
            match = True
        else:
            related_fields = [
                f.name for f in instance.__class__._meta.fields
                if f.get_internal_type() == 'ForeignKey' and f.remote_field.model.__name__ in list_class_name
            ]
            for rf in related_fields:
                match = cls.check_calculation(getattr(instance, rf))
        
        return match

    @staticmethod
    def get_members(insuree):
        if (
            insuree.family
        ):
            return list(insuree.family.members.filter(
                validity_to__isnull=True
            ))
        else:
            return [insuree]


    @classmethod
    def calculate(cls, instance, **kwargs):
        context = kwargs.get('context', None)
        if instance.__class__.__name__ == "ContractContributionPlanDetails":
            if context == 'value':
                # check type of json_ext - in case of string - json.loads
                members = cls.get_members(instance.contract_details.insuree)
                product = instance.contribution_plan.benefit_plan
                f_counts = family_counts(product, members)
                contributions = sum_contributions(product, f_counts)
                general_assembly = sum_general_assemblies(product, f_counts)
                return (contributions + general_assembly)
                
            elif context == 'members':
                return cls.get_members(instance.contract_details.insuree)
            elif context == 'validity':
                from core import datetime, datetimedelta
                validity_from = kwargs.get('validity_from', None)
                contract = None
                if instance.__class__.__name__ == "Contract":
                    contract = instance
                elif instance.__class__.__name__ == "ContractContributionPlanDetails":
                    contract = instance.contract_details.contract
                if instance.__class__.__name__ == "ContractDetails":
                    contract = instance.contract
                if contract:
                    validity_from = validity_from or contract.date_valid_from
                    date_approved = contract.date_approved or validity_from
                else:
                    date_approved = validity_from
                if not validity_from:
                    return None
                insurance_period = (
                    datetimedelta(months=product.insurance_period)
                    if product.insurance_period % 12 != 0
                    else datetimedelta(years=product.insurance_period // 12)
                )
                for i in range(4):
                    start = cycle_start(product, i, validity_from)
                    if start:
                        start_date = datetime.date.from_ad_date(start)
                    
                return {
                    'enroll_date': date_approved,
                    'start_date': date_approved,
                    'effective_date': start_date,
                    'expiry_date': (
                        datetime.date.from_ad_date(start_date)
                        + insurance_period
                        - datetimedelta(days=1)
                    ).to_ad_date()
                }
                
        else:
            user = kwargs.get('user', None)
            if user is None:
                user = User.objects.filter(i_user__id=instance.audit_user_id).first()
            cls.run_convert(instance=instance, convert_to='Invoice', user=user)
        return f"conversion finished {cls.calculation_rule_name}"

    @classmethod
    def get_linked_class(cls, sender, class_name, **kwargs):
        list_class = super().get_linked_class(sender, class_name, **kwargs)

        # because we have calculation in ContributionPlan
        #  as uuid - we have to consider this case
        if class_name == "ContributionPlan":
            list_class.append("Calculation")
        # because we have no direct relation in ContributionPlanBundle
        #  to ContributionPlan we have to consider this case
        if class_name == "ContributionPlanBundle":
            list_class.append("ContributionPlan")
        return list_class


    @classmethod
    @register_service_signal('convert_to_invoice')
    def convert(cls, instance, convert_to, **kwargs):
        # check from signal before if invoice already exist for instance
        results = {}
        signal = REGISTERED_SERVICE_SIGNALS['convert_to_invoice']
        results_check_invoice_exist = signal.signal_results['before'][0][1]
        if results_check_invoice_exist:
            convert_from = instance.__class__.__name__
            if convert_from == "Policy":
                results = cls._convert_policy(instance)
            if convert_from == "Contract":
                ccpd_list = kwargs.get('ccpd_list', None)
                results = cls._convert_contract(instance, ccpd_list=ccpd_list)
            results['user'] = kwargs.get('user', None)
        # after this method signal is sent to invoice module to save invoice data in db
        return results

    @classmethod
    def convert_batch(cls, **kwargs):
        """ function specific for informal sector """
        # TODO Informal sector / from Policy to Invoice: this function will take the all polices
        #  related to the product (all product if not specified)
        #  that have no invoice and were created in the period specified in the specified location if any
        function_arguments = kwargs.get('data')[1]
        date_from = function_arguments.get('from_date', None)
        date_to = function_arguments.get('to_date', None)
        user = function_arguments.get('user', None)
        product = function_arguments.get('product', None)
        policies_covered = Policy.objects.filter(
            Q(start_date__gte=date_from, start_date__lte=date_to, effective_date__isnull=False),
        ).order_by('start_date')
        if product:
            policies_covered = policies_covered.filter(product__id=product)
        # take all policies that have no invoice
        for policy in policies_covered:
            cls.run_convert(instance=policy, convert_to='Invoice', user=user)

    @classmethod
    def _convert_policy(cls, instance):
        invoice = PolicyToInvoiceConverter.to_invoice_obj(policy=instance)
        invoice_line_item = PolicyToLineItemConverter.to_invoice_line_item_obj(policy=instance)
        return {
            'invoice_data': invoice,
            'invoice_data_line': [invoice_line_item],
            'type_conversion': 'policy-invoice'
        }

    @classmethod
    def _convert_contract(cls, instance, **kwargs):
        invoice = ContractToInvoiceConverter.to_invoice_obj(contract=instance)
        ccpd_list = kwargs.get('ccpd_list', None)
        invoice_line_item = []
        if ccpd_list:
            for ccpd in ccpd_list:
                invoice_line_item.append(
                    ContractCpdToLineItemConverter.to_invoice_line_item_obj(contract_cpd=ccpd)
                )
        return {
            'invoice_data': invoice,
            'invoice_data_line': invoice_line_item,
            'type_conversion': 'contract-invoice'
        }
