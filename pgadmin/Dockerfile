FROM dpage/pgadmin4:latest
USER root
COPY servers.json /pgadmin4/servers.json
COPY pgpass /pgpass
RUN chown 5050:5050 /pgadmin4/servers.json /pgpass && chmod 600 /pgpass
USER 5050