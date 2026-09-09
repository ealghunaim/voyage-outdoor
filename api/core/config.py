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
    llm_api_key: str = ""

    # EVERY TASK RUNS ON THE SAME MODEL, and the tier is a cost dial that is
    # currently set to one value.
    #
    # The first draft routed one-line explanations to Haiku and the narrative to
    # Sonnet, which is the reflex from VoyageOS. It is the wrong default here.
    # Downgrading a model is a decision about output quality, and it belongs to
    # whoever owns the product, not to a table written before anything had been
    # measured. So all three tiers resolve to Opus 5 and the lever that actually
    # varies is EFFORT (gateway.TASK_EFFORT), which cuts thinking spend without
    # changing which model answers.
    #
    # To downgrade, set MODEL_SMALL=claude-haiku-4-5 in the environment. Nothing
    # in the code changes; the tier table already routes the short explanation
    # tasks to `small`. The prices below follow the model id, not the tier, so
    # ai_runs stays correct the moment you do.
    model_small: str = "claude-opus-5"
    model_mid: str = "claude-opus-5"
    model_frontier: str = "claude-opus-5"

    #: Opus 5's safety classifiers can decline a request outright. With this on,
    #: the API re-runs the declined request on Anthropic's recommended fallback
    #: inside the same call rather than handing us a refusal. Off is a supported
    #: state, not a broken one — the gateway also disables it automatically and
    #: permanently for the process if the account cannot use the beta.
    ai_server_side_fallback: bool = True

    #: Per user per day. NO LONGER A GUESS — measured in Phase 4 against the
    #: real API:
    #:
    #:     pack narrative          $0.019
    #:     ask, with a pack        $0.018
    #:     race kit, pasted list   $0.02
    #:     race kit, real page     $0.095   (Dragon's Back, 39 items, 12k chars)
    #:
    #: RAISED FROM $0.50, which was the pre-measurement guess and turns out to
    #: be five race imports. Someone planning a season in one sitting hits that,
    #: and the thing they hit it on is the feature that reads their kit list —
    #: after which the app tells them to come back tomorrow. A dollar is still
    #: negligible per user per day and buys ten imports or fifty narratives.
    #:
    #: Lower it with AI_DAILY_COST_CAP_USD if that is the wrong trade; every
    #: call prints its real cost, and ai_runs has the history to argue from.
    ai_daily_cost_cap_usd: float = 1.00

    # --- race-kit import (§24) ---
    #: A URL the user supplies is fetched BY THIS SERVER, which makes it an SSRF
    #: surface: without a guard, "http://169.254.169.254/" is a request the
    #: metadata service answers. racekit/fetch.py holds the guard; these are its
    #: numbers.
    race_kit_fetch_timeout_s: float = 20.0
    race_kit_max_bytes: int = 2_000_000

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
