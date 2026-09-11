FROM ghcr.io/home-assistant/base:3.24@sha256:93ef607824e3f27e868f11b10938283a98bf880ed57bcf8eaa81c6c2d521f6f5

ARG BUILD_VERSION=0.1.0
ARG BUILD_ARCH

LABEL \
    io.hass.name="RainPoint Local Gateway" \
  io.hass.description="Local RainPoint telemetry and bounded sensor pairing" \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}"

RUN apk add --no-cache python3 py3-pyserial rtl_433 tzdata
RUN python3 -c "import ssl; assert hasattr(ssl.SSLContext, 'set_psk_server_callback'), 'Python TLS-PSK support required'"

WORKDIR /opt/rainpoint

COPY rainpoint_protocol.py ./
COPY rainpointd ./rainpointd
COPY run.sh /

RUN chmod a+x /run.sh

EXPOSE 8787 8790

CMD ["/run.sh"]
