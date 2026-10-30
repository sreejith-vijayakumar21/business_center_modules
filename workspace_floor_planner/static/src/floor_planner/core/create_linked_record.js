import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";

/**
 * Open the business record's own form in a dialog, pre-filled by the
 * provider, and link the floor object to the record once it is saved.
 * Used by both the editor and the viewer.
 */
export async function createLinkedRecord({ api, dialog, obj, provider, onLinked }) {
    const prep = await api.prepareCreate(obj.id, provider.key);
    dialog.add(FormViewDialog, {
        resModel: prep.res_model,
        title: prep.title,
        context: prep.context,
        onRecordSaved: async (record) => {
            await api.linkCreatedRecord(obj.id, provider.key, record.resId);
            await onLinked();
        },
    });
}