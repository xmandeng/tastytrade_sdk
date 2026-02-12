from typing import Optional

from tastytrade.config import ConfigurationManager


class Credentials:
    base_url: str
    account_number: str
    is_sandbox: bool

    # OAuth2 fields (Live environment)
    oauth_client_id: Optional[str]
    oauth_client_secret: Optional[str]
    oauth_refresh_token: Optional[str]

    # Legacy fields (Sandbox environment)
    login: Optional[str]
    password: Optional[str]

    @property
    def as_dict(self) -> dict:
        return vars(self)

    def __init__(self, config: ConfigurationManager, env: str = "Test"):
        """TastyTrade credentials with environment-aware auth field loading.

        Live environment loads OAuth2 credentials (client_id, client_secret,
        refresh_token). Sandbox loads legacy credentials (login, password).

        Args:
            config: Configuration manager for reading env vars.
            env: Environment is either "Test" or "Live". Defaults to "Test".

        Raises:
            ValueError: If environment is not "Test" or "Live"
        """
        if env not in ["Test", "Live"]:
            raise ValueError("Environment must be either 'Test' or 'Live'")

        self.is_sandbox: bool = env == "Test"

        self.base_url: str = (
            config.get("TT_SANDBOX_URL")
            if self.is_sandbox
            else config.get("TT_API_URL")
        )

        self.account_number: str = (
            config.get("TT_SANDBOX_ACCOUNT")
            if self.is_sandbox
            else config.get("TT_ACCOUNT")
        )

        # Load environment-specific auth credentials
        if self.is_sandbox:
            self.login: Optional[str] = config.get("TT_SANDBOX_USER")
            self.password: Optional[str] = config.get("TT_SANDBOX_PASS")
            self.oauth_client_id: Optional[str] = None
            self.oauth_client_secret: Optional[str] = None
            self.oauth_refresh_token: Optional[str] = None
        else:
            self.login = None
            self.password = None
            self.oauth_client_id = config.get("TT_OAUTH_CLIENT_ID")
            self.oauth_client_secret = config.get("TT_OAUTH_CLIENT_SECRET")
            self.oauth_refresh_token = config.get("TT_OAUTH_REFRESH_TOKEN")


class InfluxCredentials:
    url: str
    token: str
    org: str

    def __init__(self, config: ConfigurationManager):
        self.url = config.get("INFLUX_DB_URL")
        self.org = config.get("INFLUX_DB_ORG")
        self.token = config.get("INFLUX_DB_TOKEN")
