from typing import Any, Dict, List, Optional
from app.repositories.base import BaseRepository

class BaseService:
    """
    Base Service class to encapsulate business logic.
    Interfaces with the repository layer.
    """
    def __init__(self, repository: BaseRepository):
        self.repository = repository

    def get_by_id(self, record_id: int) -> Optional[Any]:
        return self.repository.get_by_id(record_id)

    def get_all(self) -> List[Any]:
        return self.repository.get_all()

    def filter_by(self, **kwargs) -> List[Any]:
        return self.repository.filter_by(**kwargs)

    def create(self, data: Dict[str, Any], commit: bool = True) -> Any:
        entity = self.repository.model_class(**data)
        return self.repository.add(entity, commit=commit)

    def update(self, entity: Any, data: Dict[str, Any], commit: bool = True) -> Any:
        for key, value in data.items():
            if hasattr(entity, key):
                setattr(entity, key, value)
        if commit:
            self.repository.commit()
        return entity

    def delete(self, entity: Any, commit: bool = True) -> None:
        self.repository.delete(entity, commit=commit)
