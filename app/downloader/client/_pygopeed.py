import json

import requests

DEFAULT_HOST = 'http://127.0.0.1'
DEFAULT_PORT = 9999
SERVER_URI_FORMAT = '%s:%s/api/v1/tasks'


class PyGopeed:
    _secret = None
    _server_uri = None
    _headers = {}

    def __init__(self, secret=None, host=DEFAULT_HOST, port=DEFAULT_PORT):
        """
        PyGopeed constructor.

        secret: Gopeed secret token
        host: string, Gopeed rpc host, default is 'localhost'
        port: integer, Gopeed rpc port, default is 9999
        """
        if host:
            if not host.startswith('http'):
                host = "http://" + self.host
            if host.endswith('/'):
                host = self.host[:-1]

        self._server_uri = SERVER_URI_FORMAT % (host, port)
        self._secret = secret
        self._headers = {
            "Content-Type": "application/json",
            "x-api-token": f"{self._secret}" if self._secret else None
        }

    def resolveResponse(self, response):

        response_data = response.json()

        if "data" not in response_data:
            raise Exception('Gopeed接口返回解析失败')
        
        code  = response_data.get("code", -1)
        if code != 0:
            if "msg" in response_data:
                raise Exception(response_data["msg"])
            else:
                raise Exception('Gopeed接口请求失败')
        
        return response_data.get("data")

    def getAllTask(self, status=None):

        url = self._server_uri

        if status:
            if isinstance(status, list):
                url = '{}?{}'.format(self._server_uri, '&'.join(['status=' + x for x in status]))
            else:
                url = f'{self._server_uri}?status={status}'

        response = requests.get(
            url,
            headers=self._headers
        )
        
        return self.resolveResponse(response)

    def addTask(self, url, name=None, path=None, tag=None):
        labels = { "tag": tag } if tag else {}
        payload = {
            "req": { "url": url, "labels": labels },
            "opt": {
                "name": name.replace(' ', '.').strip('.') if name else '',
                "path": path.replace(' ', '.').strip('.') if path else ''
            }
        }
        response = requests.post(
            self._server_uri,
            data=json.dumps(payload),
            headers=self._headers
        )

        return self.resolveResponse(response)

    def remove(self, gid):
        """
        This method removes the download denoted by gid.

        gid: string, GID.

        return: This method returns GID of removed download.
        """
        url = f'{self._server_uri}/{gid}'

        response = requests.delete(url,headers=self._headers)

        return self.resolveResponse(response)

    def forceRemove(self, gid):
        """
        This method removes the download denoted by gid.

        gid: string, GID.

        return: This method returns GID of removed download.
        """
        url = f'{self._server_uri}/{gid}?force=true'

        response = requests.delete(url,headers=self._headers)

        return self.resolveResponse(response)

    def pause(self, gid):
        """
        This method pauses the download denoted by gid.

        gid: string, GID.

        return: This method returns GID of paused download.
        """
        
        url = f'{self._server_uri}/{gid}/pause'

        response = requests.put(url,headers=self._headers)

        return self.resolveResponse(response)

    def pauseAll(self):
        """
        This method is equal to calling Gopeed.pause() for every active/waiting download.

        return: This method returns OK for success.
        """
        url = f'{self._server_uri}/pause'

        response = requests.put(url,headers=self._headers)
        
        return self.resolveResponse(response)

    def continueOne(self, gid):
        """
        This method changes the status of the download denoted by gid from paused to waiting.

        gid: string, GID.

        return: This method returns GID of unpaused download.
        """
        url = f'{self._server_uri}/{gid}/continue'

        response = requests.put(url,headers=self._headers)
        
        return self.resolveResponse(response)

    def continueAll(self):
        """
        This method is equal to calling Gopeed.unpause() for every active/waiting download.

        return: This method returns OK for success.
        """
        url = f'{self._server_uri}/continue'

        response = requests.put(url,headers=self._headers)
        
        return self.resolveResponse(response)
