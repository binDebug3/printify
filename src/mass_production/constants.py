"""Configuration constants for the mass production automation pipeline."""

from pathlib import Path
import re

# Paths
AUTOMATION_ROOT: Path = Path(__file__).resolve().parents[3]
DATA_DIR: Path = AUTOMATION_ROOT / "data"
PROMPTS_DIR: Path = DATA_DIR / "prompts"
IMAGES_DIR: Path = DATA_DIR / "images"
META_DIR: Path = AUTOMATION_ROOT / "meta"

IDEAS_CSV_PATH: Path = DATA_DIR / "ideas.csv"
VARIANT_MAP_PATH: Path = DATA_DIR / "variant_map.json"
GEMINI_API_KEY_PATH: Path = META_DIR / "gemini_api_key.txt"
REMOVEBG_API_KEY_PATH: Path = META_DIR / "removebg_api_key.txt"
PRINTIFY_API_TOKEN_PATH: Path = META_DIR / "api_token.txt"
PRINTIFY_SHOP_ID_PATH: Path = META_DIR / "shop_id.txt"

# Prompt files
DESIGN_PROMPT_PATH: Path = PROMPTS_DIR / "design_prompt.txt"
IMAGE_PROMPT_PATH: Path = PROMPTS_DIR / "image_prompt.txt"
BACKGROUND_PROMPT_PATH: Path = PROMPTS_DIR / "background_prompt.txt"
MOCKUP_PROMPT_PATH: Path = PROMPTS_DIR / "mockup_prompt.txt"
TITLE_PROMPT_PATH: Path = PROMPTS_DIR / "title_prompt.txt"
DESCRIPTION_PROMPT_PATH: Path = PROMPTS_DIR / "description_prompt.txt"
KEYWORDS_PROMPT_PATH: Path = PROMPTS_DIR / "keywords_prompt.txt"
DEFAULT_DESCRIPTION_PATH: Path = PROMPTS_DIR / "default_description.txt"
FILTER_DESIGN_DESCRIPTIONS_PATH: Path = PROMPTS_DIR / "filter_design_descriptions.txt"

# Models and providers
TEXT_MODEL: str = "gemini-3-flash-preview"
IMAGE_MODEL: str = "gemini-3.1-flash-image-preview"
REMOVE_BG_URL: str = "https://api.remove.bg/v1.0/removebg"
PRINTIFY_API_BASE_URL: str = "https://api.printify.com/v1"
PRINTIFY_USER_AGENT: str = "printify-automation"

# Runtime behavior
IDEAS_PER_KEYWORD: int = 4
FILTERED_IDEAS_PER_KEYWORD: int = 2
FILTERED_DESIGNS_PER_KEYWORD: int = 5
DEFAULT_DRY_RUN: bool = True
MAX_KEYWORDS_PER_RUN: int = 25
MAX_GEMINI_RETRIES: int = 3
MAX_REMOVEBG_RETRIES: int = 2
MAX_PRINTIFY_RETRIES: int = 2

# Product settings
BLUEPRINT_ID: int = 706
PRINT_PROVIDER_ID: int = 99
DEFAULT_SHIRT_COLOR: str = "pepper"
BASE_PRICE_USD: float = 29.45
PRICE_STDEV_USD: float = 1.0
MIN_PRICE_USD: float = 9.99
SIZE_ORDER: list[str] = ["S", "M", "L", "XL", "2XL", "3XL", "4XL"]
SIZE_SURCHARGE_USD: dict[str, float] = {
    "2XL": 2.0,
    "3XL": 5.0,
}

# Print placement
PRINT_POSITION_X: float = 0.5
PRINT_POSITION_Y: float = 0.2
PRINT_SCALE: float = 0.65

# Naming and formatting
KEYWORDS_COUNT: int = 10
MAX_ALLOWED_TAGS: int = 13
KEYWORD_MAX_LENGTH: int = 20
CROP_CENTER_PERCENT: float = 0.8

# Etsy mockup sync
ETSY_API_BASE_URL: str = "https://openapi.etsy.com/v3/application"
ETSY_OAUTH_TOKEN_URL: str = "https://api.etsy.com/v3/public/oauth/token"
PRINTIFY_API_BASE_URL: str = "https://api.printify.com/v1"
DEFAULT_ETSY_CONFIG_PATH: Path = META_DIR / "etsy_api_key.json"
MOCKUP_FILE_PATTERN: re.Pattern[str] = re.compile(
    r"^mockup_\(.+\)_cropped\.png$",
    re.IGNORECASE,
)
