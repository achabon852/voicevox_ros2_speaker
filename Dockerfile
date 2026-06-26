FROM tiryoh/ros2:jazzy

SHELL ["/bin/bash", "-c"]

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-jazzy-rosbridge-suite \
    ros-jazzy-rmw-cyclonedds-cpp \
    libportaudio2 \
    libsndfile1 \
    python3-pip \
    pulseaudio-utils \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY src/voicevox_speaker/requirements.txt /tmp/requirements.txt
RUN pip3 install --break-system-packages -r /tmp/requirements.txt

# Build ROS2 package
WORKDIR /ros2_ws
COPY src/ src/
RUN source /opt/ros/jazzy/setup.bash \
    && colcon build --packages-select voicevox_speaker \
    && rm -rf build log

# Make workspace readable/executable by any user (UID 1000 in production)
RUN chmod -R a+rX /ros2_ws/install

# Entrypoint
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 8080 9090

ENTRYPOINT ["/docker-entrypoint.sh"]
