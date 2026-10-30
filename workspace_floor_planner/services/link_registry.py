# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.


from odoo import api, models
from odoo.exceptions import ValidationError

from odoo.addons.workspace_floor_planner.tools.constants import MAX_LINK_SEARCH_LIMIT


class WorkspaceFloorLinkRegistry(models.AbstractModel):
    """Lists the link providers available in this database.

    Extension point for bridge addons (open/closed principle)::

        class LinkRegistry(models.AbstractModel):
            _inherit = "workspace.floor.link.registry"

            @api.model
            def _get_provider_models(self):
                return super()._get_provider_models() + [
                    "workspace.floor.link.provider.meeting_room",
                ]

    Because this is an Odoo model, the list is per database: a provider only
    exists where its bridge addon is installed.
    """

    _name = "workspace.floor.link.registry"
    _description = "Floor Plan Link Registry"

    @api.model
    def _get_provider_models(self):
        return []

    @api.model
    def _get_providers(self):
        """``{link_key: provider}`` for every usable provider."""
        providers = {}
        for model_name in self._get_provider_models():
            provider = self.env[model_name]
            if provider._fp_is_usable():
                providers[provider._fp_link_key] = provider
        return providers

    @api.model
    def _get_provider(self, link_key):
        provider = self._get_providers().get(link_key)
        if provider is None:
            raise ValidationError(self.env._("Unknown link type %r.", link_key))
        return provider

    @api.model
    def _describe_providers(self):
        return [provider._fp_describe() for provider in self._get_providers().values()]

    @api.model
    def _validate_link(self, plan, object_type, link_key, res_id):
        provider = self._get_provider(link_key)
        if object_type not in provider._fp_object_types:
            raise ValidationError(self.env._(
                "A %(type)s cannot be linked to a %(target)s.",
                type=object_type, target=provider._fp_describe()["label"],
            ))
        if not isinstance(res_id, int) or isinstance(res_id, bool) or res_id <= 0:
            raise ValidationError(self.env._("Invalid linked record."))
        if not provider._fp_resolve(plan, [res_id]):
            # Same message whether it doesn't exist, is unreadable or belongs
            # to another company: we must not reveal which.
            raise ValidationError(self.env._(
                "The selected record does not exist, is not accessible to you, "
                "or belongs to another company.",
            ))

    @api.model
    def _search_targets(self, plan, link_key, query, limit):
        provider = self._get_provider(link_key)
        query = query if isinstance(query, str) else ""
        try:
            limit = max(1, min(int(limit), MAX_LINK_SEARCH_LIMIT))
        except (TypeError, ValueError):
            limit = 20
        results = provider._fp_search(plan, query.strip()[:100], limit)
        # Flag records already placed on this plan so the UI can grey them out.
        used = set(plan.object_ids.filtered(lambda o: o.link_key == link_key).mapped("link_res_id"))
        for row in results:
            row["already_placed"] = row["id"] in used
        return results

    @api.model
    def _resolve_names(self, plan, objects):
        """``{object_id: display name or None}`` for linked objects, batched
        per provider. None means the record is gone or not readable."""
        names = {}
        providers = self._get_providers()
        for link_key, group in self._group_by_provider(objects).items():
            provider = providers.get(link_key)
            by_id = {}
            # Providers are empty (falsy) recordsets: compare with None.
            if provider is not None:
                records = provider._fp_resolve(plan, group.mapped("link_res_id"))
                by_id = {rec.id: rec.display_name for rec in records}
            for obj in group:
                names[obj.id] = by_id.get(obj.link_res_id)
        return names

    @api.model
    def _group_by_provider(self, objects):
        groups = {}
        for obj in objects.filtered("link_key"):
            groups.setdefault(obj.link_key, self.env["workspace.floor.plan.object"])
            groups[obj.link_key] |= obj
        return groups

    @api.model
    def _get_open_action(self, obj):
        if not obj.link_key:
            return False
        provider = self._get_providers().get(obj.link_key)
        if provider is None:
            return False
        record = provider._fp_resolve(obj.plan_id, [obj.link_res_id])
        return provider._fp_get_open_action(record) if record else False
