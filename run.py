from app import create_app

app = create_app()

if __name__ == "__main__":
    # debug=True gives helpful error pages while developing.
    # We will turn this OFF before deploying to Render (Phase 10).
    app.run(debug=True)
