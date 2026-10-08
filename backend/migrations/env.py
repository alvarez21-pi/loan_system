import logging
from logging.config import fileConfig

from flask import current_app

from alembic import context

config = context.config
# disable_existing_loggers defaults to True, which would permanently disable
# every logger not listed in alembic.ini's [loggers] section (e.g. Flask's
# "app" logger) for the rest of the process the first time a migration runs
# in-process alongside other code (as the test suite does) — silently
# swallowing every app.logger call afterward with no error anywhere.
fileConfig(config.config_file_name, disable_existing_loggers=False)
logger = logging.getLogger("alembic.env")

config.set_main_option(
    "sqlalchemy.url",
    str(current_app.extensions["migrate"].db.get_engine().url).replace("%", "%%"),
)
target_metadata = current_app.extensions["migrate"].db.metadata


def get_metadata():
    if hasattr(target_metadata, "metadatas"):
        return target_metadata.metadatas[None]
    return target_metadata


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=get_metadata(), literal_binds=True)

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    def process_revision_directives(context, revision, directives):
        if getattr(config.cmd_opts, "autogenerate", False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info("No changes in schema detected.")

    connectable = current_app.extensions["migrate"].db.engine

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=get_metadata(),
            process_revision_directives=process_revision_directives,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
