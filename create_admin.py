
from getpass import getpass

from app import app, db, User


def create_admin():
    print("\n=== Memory Care: Create Administrator ===")

    full_name = input("Administrator full name: ").strip()
    email = input("Administrator email: ").strip().lower()

    if not full_name or not email:
        print("Name and email are required.")
        return

    if len(full_name) > 100 or len(email) > 120:
        print("Name or email is too long.")
        return

    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        print("Please enter a valid email address.")
        return

    password = getpass("Create a password (minimum 12 characters): ")
    confirm_password = getpass("Confirm password: ")

    if len(password) < 12:
        print("Password must contain at least 12 characters.")
        return

    if password != confirm_password:
        print("Passwords do not match.")
        return

    with app.app_context():
        existing_user = db.session.execute(
            db.select(User).filter_by(email=email)
        ).scalar_one_or_none()

        if existing_user:
            print(
                "That email already has an account. "
                "No changes were made."
            )
            return

        admin = User(
            full_name=full_name,
            email=email,
            role="admin"
        )
        admin.set_password(password)

        try:
            db.session.add(admin)
            db.session.commit()
            print("\nAdministrator account created successfully!")
            print("You can now sign in using the administrator email.")
        except Exception:
            db.session.rollback()
            print("Could not create the administrator account.")
            app.logger.exception("Administrator creation failed")


if __name__ == "__main__":
    create_admin()
