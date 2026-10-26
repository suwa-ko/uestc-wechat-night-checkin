FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
COPY vendor/wechat-official.deb /tmp/wechat-official.deb
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates dbus-x11 xvfb x11-utils scrot procps python3 \
       fonts-noto-cjk fontconfig libgtk-3-0t64 libasound2t64 \
       libnss3 libgbm1 libgl1 libdrm2 libxcomposite1 libxdamage1 \
       libxrandr2 libxtst6 libxkbcommon-x11-0 libxcb-cursor0 \
       libatomic1 libegl1 libegl-mesa0 libgl1-mesa-dri libpulse0 \
       x11vnc novnc websockify /tmp/wechat-official.deb \
    && rm -rf /var/lib/apt/lists/* /tmp/wechat-official.deb \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin wechat
COPY desktop/entry.sh /usr/local/bin/wechat-web-entry
RUN chmod 755 /usr/local/bin/wechat-web-entry
USER 10001:10001
ENV HOME=/home/wechat DISPLAY=:91 QT_QPA_PLATFORM=xcb XDG_RUNTIME_DIR=/tmp/wechat-runtime
WORKDIR /home/wechat
EXPOSE 6080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python3 -c "import socket,urllib.request; urllib.request.urlopen('http://127.0.0.1:6080/vnc.html',timeout=2); s=socket.create_connection(('127.0.0.1',5900),2); assert s.recv(12).startswith(b'RFB '); s.close()"
ENTRYPOINT ["/usr/local/bin/wechat-web-entry"]
