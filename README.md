# Printify Automation

[![Build Status](https://github.com/binDebug3/printify/actions/workflows/python-tests.yml/badge.svg)](https://github.com/binDebug3/printify/actions/workflows/python-tests.yml)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](./LICENSE)
[![Printify API](https://img.shields.io/badge/Printify-API-1DBA5A)](https://developers.printify.com/)
[![Gmail API](https://img.shields.io/badge/Google-Gmail%20API-EA4335?logo=gmail&logoColor=white)](https://developers.google.com/gmail/api)

Automation for two workflows:

1. Scheduled publishing of existing Printify drafts.
2. AI-assisted mass production of new listings with saved local artifacts.

## Table Of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Testing](#testing)
- [Configuration](#configuration)
- [File Architecture](#file-architecture)
- [License](#license)

## Features

- Scheduled publishing pipeline with status updates and optional notification email.
- End-to-end mass production: idea generation, filtering, image generation,
    background scene and persona generation, background removal, listing text
    generation, and Printify draft creation.
- Newly created Printify drafts are automatically appended to schedule files with
    balanced publish-date assignment in the 4-40 day window.
- Optional browser review UI for keep/retry/reject before background removal.
- Local product viewer UI for browsing posted products by tile and detail page.
- Dry-run-friendly workflow with per-design artifacts in `data/products`.
- Shirt mockup selection now balances readability with analogous color harmony,
    favoring pairings such as lighter blues on darker blues over flat same-value matches.


## Requirements

- Python 3.10 or newer.
- A Printify account, shop ID, and API token.
- A connected Etsy sales channel in Printify for publishing.
- Gemini API access for mass production.
- Gmail API credentials if email notifications are enabled.


## Installation

Using conda:

```bash
cd printify
conda env create -f requirements.yml --p printify-automation
conda activate printify-automation
```

## Usage

### Scheduled publishing

```bash
cd printify
python src/publish.py
```

Direct API helpers:

```bash
cd printify
python src/printify_api_tools/publish_product.py <product_id>
python src/printify_api_tools/get_product_info.py
python src/printify_api_tools/get_product_info.py --list-ids
python src/printify_api_tools/get_variant_info.py
```

What it does:

1. Loads `data/schedule.csv` and selects rows due today.
2. Publishes remaining drafts through Printify.
3. Updates publish status and sends notification email when configured.
4. Syncs matching Etsy mockups after publish.

### Product viewer

Browse all posted Printify products in a local visual UI:

```bash
cd printify
python src/mass_production/show_products.py
```

Manual shirt picker review UI (generates and previews color-selection mockups):

```bash
cd printify
python tests/manual/manual_test_shirt_picker.py
```

Required environment variables:

- `PRINTIFY_API_TOKEN`
- `PRINTIFY_SHOP_ID`

### Mass production

Run the pipeline:

```bash
cd printify
python src/mass_production.py
```

Generate average shirt colors from base mockups:

```bash
cd printify
python src/mass_production/photoshop/shirt_colors.py
```

Pipeline diagram:

- Mermaid flowchart source is available at `flowchart.svg`.
- Open it in a Mermaid-capable viewer (for example, Markdown preview with Mermaid support)
    to inspect the full automation flow.


Manual design review is controlled by `REVIEW_DESIGNS` in
`src/mass_production/constants.py`.

Live desktop progress dashboard is controlled by `ENABLE_PROGRESS_UI` in
`src/mass_production/constants.py`.


Core flow:

1. Read unused keywords from `data/ideas.csv`.
2. Generate and filter ideas.
3. Generate design images and optionally review/retry them.
4. Create a default color mockup from `mockup_color` by placing the generated design on
    the base shirt template.
5. Create transparent art, generate buyer and beneficiary personas with the
    mockup scene, and render final mockups.
6. Generate listing content.
7. Build and optionally post Printify products.
8. Save artifacts under `data/products/<keyword_slug>/<folder_slug>/`.
9. Mark matching ideas as published after successful posting.

Run only the manual design review UI with existing sample folders:

```bash
cd printify
python tests/manual/manual_review_ui_runner.py
```

### Post dry-run publishing

Create one Printify draft from an existing generated folder:

```bash
cd printify
python src/mass_production/post_dry_run.py <folder_slug>
```

`<folder_slug>` is resolved inside `data/products/<keyword_slug>/`.

## Testing

Run automated tests:

```bash
cd printify
pytest
```

Run a manual-only test explicitly (not part of normal `pytest` discovery):

```bash
cd printify
python -m pytest tests/manual/manual_design_crop.py::test_manual_crop_random_design_image -s
```

## Configuration

The project expects shared data and secrets outside `printify/`, as implied by the constants.py 
file.

Most runtime behavior is configured in `src/mass_production/constants.py`
(examples: `REVIEW_DESIGNS`, `IDEAS_PER_KEYWORD`,
`FILTERED_IDEAS_PER_KEYWORD`, and `BACKGROUND_REMOVAL_MODE`).


## File Architecture

```text
data/
    base_mockups/
    products/
    prompts/
    ideas.csv
    product_ids.txt
    schedule.csv
    variant_map.json
meta/
printify/
    src/
        mass_production.py
        mass_production/
            clients/
                add_etsy_mockup.py
                etsy_client.py
                gemini_client.py
                printify_client.py
            photoshop/
                design_crop.py
                io_utils.py
                remove_bg.py
            ui/
                design_review_ui.py
                progress_dashboard.py
                show_products.py
            constants.py
            models.py
            pipeline.py
            post_dry_run.py
        printify_api_tools/
            decide_bbox.py
            get_base_mockups.py
            get_product_info.py
            get_variant_info.py
            publish_product.py
        schedule/
            logger_config.py
            notification.py
            publish.py
            tools.py
    tests/
        __init__.py
        conftest.py
        artifacts/
        manual/
            manual_background_visual.py
            manual_design_crop.py
            manual_test_paste_design.py
            manual_test_progress_ui.py
            manual_review_ui_runner.py
            manual_show_products_from_data_images.py
        test_add_etsy_mockup.py
        test_design_crop.py
        test_design_review_ui.py
        test_get_base_mockups.py
        test_mass_production_cli.py
        test_mass_production_clients.py
        test_mass_production_io_utils.py
        test_mass_production_pipeline.py
        test_mass_production_post_dry_run.py
        test_notification.py
        test_publish.py
        test_tools.py
```


## Contributors

Dallin Stewart - dallinpstewart@gmail.com

## License

Licensed under the Apache License 2.0. See [LICENSE](./LICENSE).
