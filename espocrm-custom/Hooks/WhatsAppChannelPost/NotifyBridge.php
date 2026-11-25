<?php
/**
 * Notifies the GOWA bridge the moment a channel post is marked
 * "Ready to Publish", so publishing is instant instead of waiting for the
 * bridge's 60s poller. Failures are swallowed on purpose: the poller is the
 * safety net and must not be blocked by a CRM save.
 */

namespace Espo\Custom\Hooks\WhatsAppChannelPost;

use Espo\Core\Utils\Log;
use Espo\ORM\Entity;

class NotifyBridge
{
    private const BRIDGE_URL = 'http://127.0.0.1:8085/webhook/espocrm';
    private const ENV_FILE = '/data/data/com.termux/files/home/gowa-espo/.env';
    private const TRIGGER_STATUS = 'Ready to Publish';

    public function __construct(private Log $log)
    {
    }

    public function afterSave(Entity $entity, array $options = []): void
    {
        if (!$entity->isAttributeChanged('status')) {
            return;
        }

        if ($entity->get('status') !== self::TRIGGER_STATUS) {
            return;
        }

        $token = $this->readToken();

        if ($token === '') {
            $this->log->warning('WhatsAppChannelPost: bridge token missing, cannot notify bridge');

            return;
        }

        $payload = json_encode([
            'entityType' => 'WhatsAppChannelPost',
            'entityId' => $entity->getId(),
            'action' => 'publish',
        ]);

        $ch = curl_init(self::BRIDGE_URL);

        curl_setopt_array($ch, [
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => $payload,
            CURLOPT_HTTPHEADER => [
                'Content-Type: application/json',
                'X-Bridge-Token: ' . $token,
            ],
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CONNECTTIMEOUT => 2,
            CURLOPT_TIMEOUT => 4,
        ]);

        $response = curl_exec($ch);
        $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        $error = curl_error($ch);

        curl_close($ch);

        if ($response === false || $status >= 400) {
            $this->log->warning(
                'WhatsAppChannelPost: bridge notify failed (' . $status . ') ' . $error
            );

            return;
        }

        $this->log->info('WhatsAppChannelPost: bridge notified for ' . $entity->getId());
    }

    private function readToken(): string
    {
        $fromEnv = getenv('BRIDGE_TOKEN');

        if (is_string($fromEnv) && $fromEnv !== '') {
            return $fromEnv;
        }

        if (!is_readable(self::ENV_FILE)) {
            return '';
        }

        $contents = (string) file_get_contents(self::ENV_FILE);

        if (preg_match('/^BRIDGE_TOKEN=(.*)$/m', $contents, $matches)) {
            return trim($matches[1]);
        }

        return '';
    }
}
