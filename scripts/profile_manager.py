#!/usr/bin/env python3
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DEFAULT_PROFILE_PATH = Path("~/.healthfit/profile.json").expanduser()

@dataclass
class UserProfile:
    user_id: str
    display_name: str
    gender: str
    age: int
    height_cm: float
    current_weight_kg: float
    activity_level: str
    ethnicity: str = "east_asian"
    profile_complete: bool = True
    last_active: Optional[str] = None

    def touch(self) -> None:
        self.last_active = datetime.now(timezone.utc).isoformat()

class ProfileManager:
    def __init__(self, profile_path: Path = DEFAULT_PROFILE_PATH) -> None:
        self.profile_path = profile_path.expanduser()

    def exists(self) -> bool:
        return self.profile_path.exists()

    def load(self) -> UserProfile:
        payload = json.loads(self.profile_path.read_text(encoding="utf-8"))
        profile = UserProfile(**payload)
        profile.touch()
        self.save(profile)
        return profile

    def save(self, profile: UserProfile) -> None:
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile.touch()
        self.profile_path.write_text(json.dumps(asdict(profile), ensure_ascii=False, indent=2), encoding="utf-8")

    def update(self, **changes: object) -> UserProfile:
        profile = self.load()
        for key, value in changes.items():
            if not hasattr(profile, key):
                raise ValueError(f"unknown profile field: {key}")
            setattr(profile, key, value)
        self.save(profile)
        return profile

    def bootstrap(self, *, display_name: str, gender: str, age: int, height_cm: float, current_weight_kg: float, activity_level: str, ethnicity: str = "east_asian") -> UserProfile:
        profile = UserProfile(
            user_id=str(uuid.uuid4()),
            display_name=display_name,
            gender=gender,
            age=age,
            height_cm=height_cm,
            current_weight_kg=current_weight_kg,
            activity_level=activity_level,
            ethnicity=ethnicity,
        )
        self.save(profile)
        return profile
