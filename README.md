# openimis-be-calcrule-contribution-legacy_py
This repository holds the files of the openIMIS backend calculation rule contribution legacy reference module.
It is dedicated to be deployed as a module of [openimis-be_py](https://github.com/openimis/openimis-be_py). It is an 
extended part of calculation module [openimis-be-calculation_py](https://github.com/openimis/openimis-be-calculation_py) 
and therefore that module is dependent on this core calculation module. This module contains additional calculation rules. 

## Models
  - None (using no database approach for CalculationRule) - Calculation Rule is saved by defining class 
    extending the ABSCalculationClass from core module.
    
## Contexts answered for a contract contribution plan detail
  - `value`: the product contributions and general assembly fees of the insuree's family.
  - `members`: the insuree's active family members (or the insuree alone).
  - `validity`: the coverage dates, from the contribution plan's product.
    The reference date is `validity_from`, else the contract's `date_valid_from`.
    The effective date is the start of the first product cycle on or after the
    reference date; when every cycle of that year has already started, the first
    cycle of the next year; for a product without cycles, the reference date itself.
    The expiry date is the effective date plus the product insurance period, minus
    one day. A contract or a contract detail may cover several contribution plans,
    so no validity is given for them (`None`).
  - The rule applies to an object when any of its related contribution plans or
    bundles uses it.
