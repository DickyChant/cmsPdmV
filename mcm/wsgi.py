# Gunicorn configuration
import main
from tools.locator import locator as Locator

# Retrieve Flask app instance
debug = Locator().isDev()
app, _, _ = main.set_app(debug=debug)

if __name__ == '__main__':
    app.run()
