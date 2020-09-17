import requests
import logging, time

HEADERS = {'User-Agent': 'KernelCollector'}

class WebhookEmitter(object):

    def __init__(self, webhook):
        self.webhook = webhook
        self.queue = []
        self.embeds = []
        self.next_webhook = 0

    def set_webhook(self, webhook):
        self.webhook = webhook

    def add(self, message, alert=False, pre=False):
        if pre:
            message = f'```{message}```'
        if alert:
            message = '@everyone\n' + message

        for msg in [message[x:x+19980] for x in range(0, len(message), 19980)]:
            self.queue.append(msg)

    def add_embed(self, embed):
        self.embeds.append(embed)

    def try_post(self, *args, **kwargs):
        try:
            req = requests.post(*args, **kwargs)

            try:
                req = req.json()
            except:
                return True

            if 'retry_after' in req:
                time.sleep((req['retry_after'] / 1000) + 0.1)
                return self.try_post(*args, **kwargs)
        except:
            print('Could not send request... trying again.')
            time.sleep(1)
            return self.try_post(*args, **kwargs)

    def send_webhook(self, data):
        current_time = time.time()

        if self.next_webhook > current_time:
            time.sleep(self.next_webhook - current_time)

        result = self.try_post(self.webhook, headers=HEADERS, json=data)
        self.next_webhook = time.time() + 2
        return result

    def send_all(self):
        for item in self.queue:
            logging.info(item)

        for embed in self.embeds:
            for part in embed.get('embeds', []):
                for line in part.get('description', '').split('\n'):
                    logging.info(line)

        if not self.webhook:
            # We don't have a webhook, let's just clear the queue.
            self.queue = []
            self.embeds = []
            return

        while self.queue:
            current_item = self.queue.pop(0)

            while self.queue:
                item = self.queue.pop(0)

                if (len(item) + len(current_item)) > 19980:
                    self.send_webhook({'content': current_item})
                    current_item = item
                else:
                    current_item += '\n'
                    current_item += item

            self.send_webhook({'content': current_item})

        while self.embeds:
            self.send_webhook(self.embeds.pop(0))
