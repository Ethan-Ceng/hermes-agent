"""Owned API business store lifetime;closing releases the same captured resource."""

class OwnedApiStore:
    def __init__(self, store, resource):
        self._api_store, self._resource = store, resource

    def __getattr__(self, name):
        return getattr(self._api_store, name)

    def __len__(self):
        return len(self._api_store)

    @property
    def is_open(self):
        return self._resource.is_open and not self._api_store._closed

    def close(self):
        try:
            self._api_store.close()
        finally:
            self._resource.close()
