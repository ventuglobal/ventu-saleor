.PHONY: up down logs bootstrap provision storefront-add storefront-pull

# Levantar el stack local
up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

# Primer arranque de Saleor: migraciones + superuser + datos demo (opcional)
bootstrap:
	docker compose run --rm api python manage.py migrate
	docker compose run --rm api python manage.py createsuperuser
	@echo "Opcional: docker compose run --rm api python manage.py populatedb"

# Crear warehouse VENTU + channels y reportar los gid para el backend Ventu
provision:
	SALEOR_API_URL=$${SALEOR_API_URL:-http://localhost:8000/graphql/} \
	python scripts/provision.py --channels $${CHANNELS:-retail-cl,b2b-cl}

# Storefront: traer el oficial como subtree (ver README "upstream-sync")
storefront-add:
	git remote add upstream https://github.com/saleor/storefront.git || true
	git subtree add --prefix=storefront upstream main --squash

storefront-pull:
	git subtree pull --prefix=storefront upstream main --squash
