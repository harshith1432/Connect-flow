from typing import Type, TypeVar, Generic, List, Optional, Any
from app.extensions import db

T = TypeVar('T')

class BaseRepository(Generic[T]):
    """
    Base Repository class to encapsulate database access logic.
    Provides standard CRUD operations for all SQLAlchemy models.
    """
    def __init__(self, model_class: Type[T]):
        self.model_class = model_class

    def get_by_id(self, record_id: int) -> Optional[T]:
        """Fetch a record by its primary key."""
        return db.session.get(self.model_class, record_id)

    def get_all(self) -> List[T]:
        """Fetch all records for the model."""
        return self.model_class.query.all()

    def filter_by(self, **kwargs: Any) -> List[T]:
        """Fetch records matching the provided keyword arguments."""
        return self.model_class.query.filter_by(**kwargs).all()

    def filter_by_first(self, **kwargs: Any) -> Optional[T]:
        """Fetch the first record matching the provided keyword arguments."""
        return self.model_class.query.filter_by(**kwargs).first()

    def add(self, entity: T, commit: bool = True) -> T:
        """Add a new record to the database."""
        db.session.add(entity)
        if commit:
            self.commit()
        return entity

    def delete(self, entity: T, commit: bool = True) -> None:
        """Delete a record from the database."""
        db.session.delete(entity)
        if commit:
            self.commit()

    def commit(self) -> None:
        """Commit the current database transaction."""
        db.session.commit()

    def rollback(self) -> None:
        """Rollback the current database transaction."""
        db.session.rollback()
