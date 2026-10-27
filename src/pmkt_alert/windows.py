import calendar
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Windows:
    as_of: date

    def _back(self, start: int, end: int) -> tuple[date, date]:
        return self.as_of - timedelta(days=start), self.as_of - timedelta(days=end)

    @property
    def l7d(self) -> tuple[date, date]:
        return self._back(6, 0)

    @property
    def p7d(self) -> tuple[date, date]:
        return self._back(13, 7)

    @property
    def l3d(self) -> tuple[date, date]:
        return self._back(2, 0)

    @property
    def mtd(self) -> tuple[date, date]:
        return self.as_of.replace(day=1), self.as_of

    @property
    def days_in_month(self) -> int:
        return calendar.monthrange(self.as_of.year, self.as_of.month)[1]

    @property
    def time_gone(self) -> float:
        return self.as_of.day / self.days_in_month


def default_as_of(inputs) -> date:
    return min(inputs.raw["date"].max(), inputs.ads["date"].max())
