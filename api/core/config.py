"""Config — model IDs, budgets and provider keys live HERE, never in call sites.

load_dotenv puts .env into the real process environment rather than only into
this Settings class. Pydantic reads .env to populate fields and stops there, so
anything consulting os.environ directly sees nothing locally while working
perfectly on a host where the variables genuinely are in the environment. That
is a failure that only appears on one machine, which is the kind that gets
debugged twice.
"""
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv(override=False)  # a real env var always beats the file


class Settings(BaseSettings):
    env: str = "local"

    # --- Supabase (its OWN project — never VoyageOS's) ---
    supabase_url: str = ""
    supabase_service_key: str = ""       # server-side only, never shipped to the app
    dev_user_id: str = ""                # local stand-in for a signed-in user

    # --- AI gateway ---
    # Nothing calls a model until Phase 4. These are here from commit one so the
    # routing table has somewhere to resolve against and so ai_runs can be wired
    # before there is anything to log.
    llm_api_key: str = ""
    model_small: str = "claude-haiku-4-5"
    model_mid: str = "claude-sonnet-5"
    model_frontier: str = "claude-opus-5"
    #: Per user per day. VoyageOS runs $0.50 for trip guides; a Smart Pack
    #: narrative over a full gear locker is a different prompt size and this
    #: number is a guess until Phase 3/4 measures it. Audit risk #7.
    ai_daily_cost_cap_usd: float = 0.50

    # --- the coarse gate ---
    #: Required on every request except the open paths in main.py. Rotating a
    #: single value 401s every user still on the old build, and store updates
    #: are neither instant nor universal — so a rotation overlaps, exactly like
    #: a migration does. EMPTY IS THE NORMAL STATE for the previous key.
    app_shared_secret: str = ""
    app_shared_secret_previous: str = ""

    # extra="ignore" tolerates env vars this class does not model. VoyageOS
    # needed it for versioned key names (MASTER_KEK_V1, _V2 …) that no settings
    # class can declare a field per; without it, adding one to .env fails
    # validation at import and takes down every module that touches settings.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
