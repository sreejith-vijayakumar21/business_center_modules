import { Component, onWillUpdateProps, useState } from "@odoo/owl";
import { useDebounced } from "@web/core/utils/timing";

/**
 * Searchable picker that links a rentable object to an existing business
 * record supplied by a link provider (bridge addon). The server decides
 * which records may be offered; this component only displays them.
 */
export class LinkSelector extends Component {
    static template = "workspace_floor_planner.LinkSelector";
    static props = {
        object: Object,
        providers: Array,
        api: Object,
        readonly: Boolean,
        onLink: Function,
        onOpen: Function,
    };

    setup() {
        this.state = useState({
            providerKey: this.props.object.link_key || this.props.providers[0]?.key,
            query: "",
            results: [],
            searching: false,
            open: false,
        });
        this.debouncedSearch = useDebounced(() => this.search(), 250);
        onWillUpdateProps((next) => {
            if (next.object.key !== this.props.object.key) {
                Object.assign(this.state, {
                    providerKey: next.object.link_key || next.providers[0]?.key,
                    query: "",
                    results: [],
                    open: false,
                });
            }
        });
    }

    get provider() {
        return this.props.providers.find((p) => p.key === this.state.providerKey);
    }

    get isLinkSaved() {
        return Boolean(this.props.object.id && !this.props.object.link_restricted);
    }

    async search() {
        if (!this.provider) {
            return;
        }
        this.state.searching = true;
        try {
            this.state.results = await this.props.api.searchLinkTargets(this.provider.key, this.state.query);
            this.state.open = true;
        } finally {
            this.state.searching = false;
        }
    }

    onQueryInput(ev) {
        this.state.query = ev.target.value;
        this.debouncedSearch();
    }

    onProviderChange(ev) {
        this.state.providerKey = ev.target.value;
        this.state.results = [];
    }

    pick(record) {
        this.props.onLink(this.provider, record);
        this.state.open = false;
        this.state.query = "";
    }
}
