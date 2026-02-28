from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from .extensions import db
from .models.user import User
# tu peux ajouter d'autres modèles ici

def init_admin(app):
    admin = Admin(app, name="DealNova Admin")  # template_mode supprimé

    admin.add_view(ModelView(User, db.session))
    # admin.add_view(ModelView(OtherModel, db.session))
    return admin
