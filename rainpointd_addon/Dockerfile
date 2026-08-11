FROM ghcr.io/home-assistant/base:latest

ARG BUILD_VERSION=0.1.0
ARG BUILD_ARCH

LABEL \
    io.hass.name="RainPoint Local Gateway" \
  io.hass.description="Local RainPoint telemetry and bounded sensor pairing" \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}"

RUN apk add --no-cache python3 py3-pyserial rtl_433

WORKDIR /opt/rainpoint

COPY rainpoint_protocol.py fixtures.json ./
COPY rainpointd ./rainpointd
COPY run.sh /

RUN chmod a+x /run.sh

EXPOSE 8787 8790

CMD ["/run.sh"]
