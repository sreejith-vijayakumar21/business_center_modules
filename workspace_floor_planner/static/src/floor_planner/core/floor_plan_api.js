/**
 * The only place the editor talks to the server. Components receive an
 * instance of this class instead of calling the ORM directly, so the
 * transport can be swapped or mocked in tests.
 */
export class FloorPlanApi {
    constructor(orm, planId) {
        this.orm = orm;
        this.planId = planId;
        this.model = "workspace.floor.plan";
    }

    _call(method, args = [], kwargs = {}) {
        return this.orm.call(this.model, method, [[this.planId], ...args], kwargs);
    }

    load() {
        return this._call("fp_load_layout");
    }

    save(payload) {
        return this._call("fp_save_layout", [payload]);
    }

    statuses(at = false) {
        return this._call("fp_get_statuses", [at || false]);
    }

    searchLinkTargets(linkKey, query, limit = 20) {
        return this._call("fp_search_link_targets", [linkKey, query, limit]);
    }

    openLinkedRecordAction(objectId) {
        return this._call("fp_open_linked_record", [objectId]);
    }

    prepareCreate(objectId, linkKey) {
        return this._call("fp_prepare_create", [objectId, linkKey]);
    }

    linkCreatedRecord(objectId, linkKey, resId) {
        return this._call("fp_link_created_record", [objectId, linkKey, resId]);
    }
}
