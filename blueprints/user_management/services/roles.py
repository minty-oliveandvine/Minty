from models.user_management import Roles


def get_all_roles():
    return Roles.query.all()
