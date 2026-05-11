---
name: labware
description: Available labware definitions, usage, and valid row/column coordinates.
---

# Critical Rule

If you are unsure which labware or well should be used when generating commands, **ask the user** before proceeding.  
Do **not** assume.

If there is only one well, `well_name` can be assumed to be `A1`

# Labware Reference

This reference defines each available labware, what it is used for, and its valid row/column coordinates.

## `MEA_cell_MTP`

- **Purpose:** Single-position plate location used for the MEA cell target.
- **Rows:** `A` (1 row)
- **Columns:** `1` (1 column)
- **Total wells:** 1

## `opentrons_96_tiprack_300ul`

- **Purpose:** 300 uL pipette tip rack for standard liquid handling steps.
- **Rows:** `A-H` (8 rows)
- **Columns:** `1-12` (12 columns)
- **Total well:** 96

## `polyelectric_8_wellplate_30000ul`

- **Purpose:** 8-well high-volume plate (30,000 uL per well) for large-volume samples/reagents.
- **Rows:** `A-B` (2 rows)
- **Columns:** `1-4` (4 columns)
- **Total wells:** 8

## `sartorious_96_tiprack_1000ul`

- **Purpose:** 1000 uL pipette tip rack for high-volume transfers.
- **Rows:** `A-H` (8 rows)
- **Columns:** `1-12` (12 columns)
- **Total wells:** 96

## Opentrons Labware
### Standard Labware

#### `corning_96_wellplate_360ul_flat`

- **Purpose:** Standard flat-bottom 96-well plate for general liquid handling and transfers.
- **Rows:** `A-H` (8 rows)
- **Columns:** `1-12` (12 columns)
- **Total wells:** 96
- **Well volume:** 360 uL

#### `corning_384_wellplate_112ul_flat`

- **Purpose:** High-density flat-bottom 384-well plate for high-throughput assays.
- **Rows:** `A-P` (16 rows)
- **Columns:** `1-24` (24 columns)
- **Total wells:** 384
- **Well volume:** 112 uL

#### `opentrons_96_tiprack_10ul`

- **Purpose:** 10 uL pipette tip rack for very low-volume transfers.
- **Rows:** `A-H` (8 rows)
- **Columns:** `1-12` (12 columns)
- **Total wells:** 96

#### `opentrons_96_tiprack_20ul`

- **Purpose:** 20 uL pipette tip rack for low-volume transfers.
- **Rows:** `A-H` (8 rows)
- **Columns:** `1-12` (12 columns)
- **Total wells:** 96

#### `opentrons_96_tiprack_300ul`

- **Purpose:** 300 uL pipette tip rack for standard liquid handling.
- **Rows:** `A-H` (8 rows)
- **Columns:** `1-12` (12 columns)
- **Total wells:** 96

#### `opentrons_96_tiprack_1000ul`

- **Purpose:** 1000 uL pipette tip rack for high-volume transfers.
- **Rows:** `A-H` (8 rows)
- **Columns:** `1-12` (12 columns)
- **Total wells:** 96

#### `nest_12_reservoir_15ml`

- **Purpose:** 12-channel reservoir for multi-reagent workflows or column-wise dispensing.
- **Rows:** `A` (1 row)
- **Columns:** `1-12` (12 columns)
- **Total wells:** 12
- **Well volume:** 15,000 uL per well

#### `nest_96_wellplate_100ul_pcr_full_skirt`

- **Purpose:** Full-skirt 96-well PCR plate for PCR reactions and sample storage.
- **Rows:** `A-H` (8 rows)
- **Columns:** `1-12` (12 columns)
- **Total wells:** 96
- **Well volume:** 100 uL

#### `nest_96_wellplate_200ul_flat`

- **Purpose:** Flat-bottom 96-well plate for general transfers, assays, and sample prep.
- **Rows:** `A-H` (8 rows)
- **Columns:** `1-12` (12 columns)
- **Total wells:** 96
- **Well volume:** 200 uL

### Custom Labware

#### `mass_balance_vial_30000`

- **Display name:** AMDM Mass Balance with 30mL vial
- **Brand:** AMDM (`amdm_balance_vial_30ml`)
- **Purpose:** Single-position vial on a mass balance for gravimetric liquid handling.
- **Rows:** `A` (1 row)
- **Columns:** `1` (1 column)
- **Total wells:** 1
- **Well:** `A1` — circular, diameter 17.0 mm, depth 56 mm
- **Well volume:** 30,000 uL
- **Namespace:** `custom_beta`
- **JSON file:** `opentrons/driver/src/opentrons_driver/labware/mass_balance_vial_30000.json`

#### `mass_balance_vial_50000`

- **Display name:** AMDM Mass Balance with 50mL vial
- **Brand:** AMDM (`amdm_balance_vial_50ml`)
- **Purpose:** Single-position vial on a mass balance for gravimetric liquid handling with higher capacity.
- **Rows:** `A` (1 row)
- **Columns:** `1` (1 column)
- **Total wells:** 1
- **Well:** `A1` — circular, diameter 17.5 mm, depth 56 mm
- **Well volume:** 50,000 uL
- **Namespace:** `custom_beta`
- **JSON file:** `opentrons/driver/src/opentrons_driver/labware/mass_balance_vial_50000.json`

## `trash_bin`

- **Purpose:** Single-position waste location for tip discard.
- **Rows:** `A` (1 row)
- **Columns:** `1` (1 column)
- **Total wells:** `A1`
