# Printify Automation

[![Build Status](https://github.com/binDebug3/printify/actions/workflows/python-tests.yml/badge.svg)](https://github.com/binDebug3/printify/actions/workflows/python-tests.yml)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](./LICENSE)
[![Printify API](https://img.shields.io/badge/Printify-API-1DBA5A)](https://developers.printify.com/)
[![Gmail API](https://img.shields.io/badge/Google-Gmail%20API-EA4335?logo=gmail&logoColor=white)](https://developers.google.com/gmail/api)

Automation for two related workflows:

1. Scheduled publication of existing Printify drafts to Etsy.
2. AI-assisted mass production of new shirt listings, including dry runs, Printify draft creation, and artifact generation.

The repository uses CSV- and file-based configuration under the workspace root, writes action logs to `meta/actions.log`, and stores generated listing assets under `data/images`.

## Table Of Contents

- [Features](#features)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Configuration](#configuration)
- [Installation](#installation)
- [Usage](#usage)
- [Testing](#testing)
- [License](#license)

## Features

- Scheduled Etsy publishing from `data/schedule.csv` through the Printify publish API.
- CSV write-back of `publish_status` after successful scheduled publishes.
- Delayed Etsy mockup sync after publish, using `data/images/<nick_name>/mockup_(color)_cropped.png` as the primary listing image.
- Optional Gmail notifications when scheduled products go live.
- Product utility commands for listing shop products and generating color-to-variant maps.
- Mass production pipeline driven by `data/ideas.csv` and prompt templates in `data/prompts`.
- Gemini-powered idea generation, listing copy generation, and image generation.
- remove.bg integration for transparent artwork generation.
- Printify dry-run and real-run support for draft product creation.
- LLM-based design filtering from generated ideas down to `FILTERED_IDEAS_PER_KEYWORD` before image generation.
- Optional browser-based design review UI for keep/retry/reject decisions before background removal.
- Per-design artifact output under `data/images/<folder_slug>/`, including prompts, listing text, payloads, and API responses.
- Post-dry-run command for creating a single Printify draft from an existing generated folder.
- ideas.csv publication tracking: after successful mass-production publishes, eligible `used=false` rows are updated to `used=true`, `shirt_count=IDEAS_PER_KEYWORD`, and today's `publication_date`.
- Console and log messaging when no unused ideas are available for mass production.

## Project Structure

```text
data/
    images/
    prompts/
meta/
printify/
    src/
        logger_config.py
        mass_production.py
        notification.py
        publish.py
        tools.py
        mass_production/
            add_etsy_mockup.py
            constants.py
            gemini_client.py
            io_utils.py
            models.py
            pipeline.py
            post_dry_run.py
            printify_client.py
            remove_bg.py
    tests/
        __init__.py
        conftest.py
        test_mass_production_io_utils.py
        test_notification.py
        test_publish.py
        test_tools.py
```

## Requirements

- Python 3.10 or newer.
- A Printify account, shop ID, and API token.
- A connected Etsy sales channel in Printify for publishing.
- Gemini API access for mass production.
- remove.bg API access for transparent artwork generation.
- Gmail API credentials if email notifications are enabled.

Primary Python dependencies used in this project:

- pandas
- requests
- pillow
- google-genai
- google-auth
- google-auth-oauthlib
- google-api-python-client

## Configuration

The project expects the workspace layout shown above, with shared data and secrets outside the `printify/` folder.

Required data and config files:

- `../data/schedule.csv` for scheduled publishing.
- `../data/ideas.csv` for mass production input and publication tracking.
- `../data/variant_map.json` for mapping shirt colors to Printify variant IDs.
- `../data/prompts/*.txt` for mass production prompt templates.
- `../meta/api_token.txt` for the Printify API token.
- `../meta/shop_id.txt` for the Printify shop ID.
- `../meta/gemini_api_key.txt` for the Gemini API key.
- `../meta/removebg_api_key.txt` for the remove.bg API key.
- `../meta/etsy_api_key.json` for Etsy API credentials and Etsy shop ID.
- `../meta/email_address.txt` for the notification recipient.
- `../meta/cal_credentials.json` for Gmail OAuth credentials.

Mass production background removal is controlled in `src/mass_production/constants.py`
with `BACKGROUND_REMOVAL_MODE`. Use `"api"` to call remove.bg or `"manual"` to make
either pure white or pure black pixels transparent, whichever removes more pixels.

### schedule.csv

The scheduled publishing workflow expects these columns:

- `publish_date` in `MM/DD/YYYY` format.
- `shop_id`
- `product_id`
- `nick_name`
- `publish_status`

## Installation

Using conda:

```bash
cd printify
conda env create -f requirements.yml
conda activate printify-automation
```

If you already have an environment and just want the packages:

```bash
cd printify
pip install pandas requests pillow google-genai google-auth google-auth-oauthlib google-api-python-client
```

## Usage

### Scheduled publishing

Run the scheduled Etsy publishing job:

```bash
cd printify
python src/publish.py
```

What it does:

1. Loads `data/schedule.csv`.
2. Filters rows scheduled for today.
3. Skips rows already marked `publish_status=True`.
4. Publishes remaining drafts through Printify.
5. Marks successful rows as published.
6. Sends notification emails when configured.
7. Waits one minute, then uploads the matching custom mockup to the Etsy listing.
8. Writes the updated schedule back to disk.

### Shop utilities

Export all Printify product IDs:

```bash
cd printify
python src/tools.py get_all_product_ids
```

Generate `data/variant_map.json` for a blueprint and print provider:

```bash
cd printify
python src/tools.py get_printify_variant_ids
```

### Mass production

Run the generation pipeline:

```bash
cd printify
python src/mass_production.py
```

For real-time terminal logs when using conda, prefer:

```bash
cd printify
conda run --no-capture-output -n lila python -u .\src\mass_production.py --real-run
```

Run with manual design review enabled:

```bash
cd printify
python src/mass_production.py --review-designs
```

What the mass production pipeline does:

1. Reads unused keywords from `data/ideas.csv`.
2. Generates ideas from the prompt templates.
3. Filters generated ideas using `data/prompts/filter_design_descriptions.txt`, then stores filter metadata in `data/images/<keyword_slug>_filtering.json`.
4. Generates design images for the filtered ideas.
5. Optional `--review-designs` step: opens a local browser UI to keep, retry once, or reject each design before background removal. The review summary is saved to `data/images/<keyword_slug>_design_review.json`.
6. Produces transparent artwork and mockups.
7. Generates listing title, description, personas, and keyword tags.
8. Builds Printify payloads and optionally creates draft products.
9. Saves all generated artifacts under `data/images/<folder_slug>/`.
10. Updates matching `ideas.csv` rows after successful publishing.

If there are no rows with `used=false`, the pipeline logs and prints a message instead of running.

### Post dry-run publishing

Create one Printify draft from an existing generated folder:

```bash
cd printify
python src/mass_production/post_dry_run.py <folder_slug>
```

This command expects the folder under `data/images/` to contain the dry-run artifacts needed to rebuild the final Printify payload.

## Testing

Run the full test suite:

```bash
cd printify
pytest
```

## Contributors

Dallin Stewart - dallinpstewart@gmail.com

## License

Licensed under the Apache License 2.0. See [LICENSE](./LICENSE).
