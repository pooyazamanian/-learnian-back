"""Auth bounded context: phone sign-in, sessions and refresh tokens.

Layout follows the dependency rule (outer layers know inner ones, never the
reverse):

``domain``       pure rules and time/phone normalization, no I/O
``application``  use cases and the ports they depend on
``infrastructure`` SQLAlchemy models, repositories, JWT and SMS adapters
``presentation`` FastAPI router, schemas and dependency wiring

The package deliberately imports nothing: importing the router here would make
every ``auth.models`` import pull in FastAPI and create an import cycle with the
modules that auth itself depends on. Routers are attached in ``lurnian.api``.
"""
