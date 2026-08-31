CREATE DATABASE IF NOT EXISTS jetrover CHARACTER SET utf8mb4;
USE jetrover;
CREATE TABLE IF NOT EXISTS ros_events (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  topic VARCHAR(96) NOT NULL,
  event_time TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  payload JSON NOT NULL,
  INDEX idx_topic_time(topic,event_time)
);
CREATE TABLE IF NOT EXISTS detected_objects (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  label VARCHAR(96) NOT NULL, confidence FLOAT NULL,
  map_x FLOAT NULL, map_y FLOAT NULL, seen_at TIMESTAMP NOT NULL,
  raw JSON NOT NULL, INDEX idx_object_time(label,seen_at)
);
