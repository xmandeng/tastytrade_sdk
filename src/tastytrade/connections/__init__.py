from tastytrade.config import ConfigurationManager


class Credentials:
    base_url: str
    is_sandbox: bool
    oauth_client_id: str
    oauth_client_secret: str
    oauth_refresh_token: str

    @property
    def as_dict(self) -> dict:
        return vars(self)

    def __init__(self, config: ConfigurationManager, env: str = "Test"):
        """Tastytrade OAuth2 credentials read from environment variables.

        Args:
            env: Environment is either "Test" or "Live". Defaults to "Test".

        Raises:
            ValueError: If environment is not "Test" or "Live"
        """
        if env not in ["Test", "Live"]:
            raise ValueError("Environment must be either 'Test' or 'Live'")

        self.base_url: str = (
            config.get("TT_SANDBOX_URL") if env == "Test" else config.get("TT_API_URL")
        )

        self.account_number: str = (
            config.get("TT_SANDBOX_ACCOUNT")
            if env == "Test"
            else config.get("TT_ACCOUNT")
        )

        self.oauth_client_id: str = config.get("TT_OAUTH_CLIENT_ID")
        self.oauth_client_secret: str = config.get("TT_OAUTH_CLIENT_SECRET")
        self.oauth_refresh_token: str = config.get("TT_OAUTH_REFRESH_TOKEN")

        self.is_sandbox: bool = env == "Test"


class InfluxCredentials:
    url: str
    token: str
    org: str

    def __init__(self, config: ConfigurationManager):
        self.url = config.get("INFLUX_DB_URL")
        self.org = config.get("INFLUX_DB_ORG")
        self.token = config.get("INFLUX_DB_TOKEN")
