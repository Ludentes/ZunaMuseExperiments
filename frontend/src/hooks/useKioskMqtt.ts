import { useCallback, useEffect, useRef, useState } from "react";
import mqtt from "mqtt";

export interface KioskMqttConfig {
  brokerUrl: string;
  kioskSlug: string;
}

const DEFAULT_CONFIG: KioskMqttConfig = {
  brokerUrl: "ws://192.168.87.102:49001",
  kioskSlug: "kiosk-1-2",
};

export function useKioskMqtt(enabled: boolean, config: KioskMqttConfig = DEFAULT_CONFIG) {
  const clientRef = useRef<mqtt.MqttClient | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!enabled) {
      if (clientRef.current) {
        clientRef.current.end(true);
        clientRef.current = null;
        setConnected(false);
      }
      return;
    }

    const client = mqtt.connect(config.brokerUrl, {
      clientId: `euterpe-bci-${Date.now()}`,
      reconnectPeriod: 5000,
      connectTimeout: 3000,
      clean: true,
    });

    client.on("connect", () => setConnected(true));
    client.on("close", () => setConnected(false));
    client.on("error", (err) => console.warn("[MQTT]", err.message));

    clientRef.current = client;

    return () => {
      client.end(true);
      clientRef.current = null;
      setConnected(false);
    };
  }, [enabled, config.brokerUrl]);

  const sendPlayback = useCallback(
    (action: string) => {
      const client = clientRef.current;
      if (!client || !connected) return;
      const topic = `umka/kiosks/${config.kioskSlug}/commands/playback`;
      client.publish(topic, JSON.stringify({ action }));
    },
    [connected, config.kioskSlug],
  );

  return { connected, sendPlayback };
}
