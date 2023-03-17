# Monte Carlo Management application

Environment variables
----------------------
- COUCH_CRED:  Path to a JSON file with the credentials to authenticate against CouchDB
	           Required keys: {"username": <USERNAME>, "password": <PASSWORD>}
- USERCRT: Path to the VOMS certificate. The certificate must use the PEM format
- USERKEY: Path to the certificate private key. The key must use the PEM format
- CRED_FILE: Path to a JSON file with the service account credentials to open SSH connections
             Required keys: {"username": <USERNAME>, "password": <PASSWORD>}
- PRODUCTION: "True" if it is required to deploy the application as production environment

Optional environment variables
-------------------------------
The following environment variables allow the user to override some default configurations
available inside the tools/locator.py file

- COUCH_DATABASE_URL: Access URL to CouchDB
- LUCENE_URL: Access URL to Lucene engine for querying CouchDB
- BASE_URL: Application access URL. This is mainly used for components which send emails and notifications

Web server configuration
-------------------------------
Override the following environment variables if desired

- MCM_HOST: Hostname to listen. Default: 0.0.0.0
- MCM_PORT: Application port. Default: 8000