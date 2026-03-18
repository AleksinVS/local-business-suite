from django.db import models


class Department(models.Model):
    name = models.CharField("Название", max_length=255)
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="children",
        verbose_name="Родительское подразделение",
    )

    class Meta:
        ordering = ["parent__id", "name", "id"]
        unique_together = ("parent", "name")
        verbose_name = "Подразделение"
        verbose_name_plural = "Подразделения"

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        if self.parent_id:
            return f"{self.parent.full_name} / {self.name}"
        return self.name

    @property
    def indented_name(self):
        depth = 0
        node = self.parent
        while node is not None:
            depth += 1
            node = node.parent
        prefix = "\u00a0\u00a0" * depth
        return f"{prefix}{self.name}"

    def descendant_ids(self):
        children_map = {}
        for department in Department.objects.select_related("parent").order_by("name", "id"):
            children_map.setdefault(department.parent_id, []).append(department.id)
        collected = []
        stack = [self.id]
        while stack:
            current = stack.pop()
            collected.append(current)
            stack.extend(children_map.get(current, []))
        return collected
