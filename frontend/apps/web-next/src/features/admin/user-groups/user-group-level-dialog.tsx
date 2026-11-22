import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { Selector } from "@astryxdesign/core/Selector";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { useId, useRef, useState } from "react";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { useReturnFocus } from "@/components/ui/dialog-focus";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import { LevelImpact } from "@/features/admin/security-classifications/level-impact";
import {
  highestFirst,
  securityClassificationsQueryOptions,
  type SecurityClassification
} from "@/features/admin/security-classifications/security-classifications";
import { USER_GROUPS_KEY, type UserGroup, userGroupLevelQueryOptions } from "./user-groups";

const NO_LEVEL = "__none__";

function LevelForm({
  formId,
  group,
  classifications,
  currentId,
  onSaved,
  onPendingChange
}: {
  formId: string;
  group: UserGroup;
  classifications: SecurityClassification[];
  currentId: string | null;
  onSaved: () => void;
  onPendingChange: (pending: boolean) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [value, setValue] = useState(currentId ?? NO_LEVEL);

  const save = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.PUT("/api/v1/user-groups/{id}/security-classification/", {
          params: { path: { id: group.id } },
          body: { security_classification: value === NO_LEVEL ? null : { id: value } }
        })
      ),
    onMutate: () => onPendingChange(true),
    onSettled: () => onPendingChange(false),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: USER_GROUPS_KEY });
      toast.success(t("admin_user_groups_level_saved", { name: group.name }));
      onSaved();
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <form
      id={formId}
      noValidate
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!save.isPending) save.mutate();
      }}
    >
      <Selector
        label={t("user_group_security_level")}
        description={t("user_group_security_level_description")}
        options={[
          { value: NO_LEVEL, label: t("user_group_no_security_level") },
          ...classifications.map((item) => ({ value: item.id, label: item.name }))
        ]}
        value={value}
        onChange={(next) => setValue(next as string)}
        width="100%"
      />
      {value !== (currentId ?? NO_LEVEL) && (
        <LevelImpact classificationId={value === NO_LEVEL ? null : value} userGroupId={group.id} />
      )}
    </form>
  );
}

/** Set the security level the members of `group` work at. */
export function UserGroupLevelDialog({
  group,
  open,
  onOpenChange
}: {
  group: UserGroup | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const formId = useId();
  const [pending, setPending] = useState(false);
  // Opened from a row menu, whose item is gone by the time the dialog is up.
  const noTrigger = useRef<HTMLElement | null>(null);
  useReturnFocus(open, noTrigger);

  // The list is open to every member and leaves the level out: read the group itself.
  const level = useQuery({
    ...userGroupLevelQueryOptions(browserApi, group?.id ?? ""),
    enabled: open && group !== null
  });
  const classifications = useQuery({
    ...securityClassificationsQueryOptions(browserApi),
    enabled: open
  });

  function requestOpenChange(next: boolean) {
    if (!next && pending) return;
    onOpenChange(next);
  }

  return (
    <Dialog isOpen={open} onOpenChange={requestOpenChange} purpose="form" width={520}>
      <Layout
        height="auto"
        header={
          <DialogHeader
            title={t("user_group_security_level_title", { name: group?.name ?? "" })}
            onOpenChange={requestOpenChange}
          />
        }
        content={
          open && group ? (
            <LayoutContent>
              <QueryStateBoundary queries={[level, classifications]} rows={2}>
                {() => (
                  <LevelForm
                    key={group.id}
                    formId={formId}
                    group={group}
                    classifications={highestFirst(
                      classifications.data?.security_classifications ?? []
                    )}
                    currentId={level.data?.security_classification_id ?? null}
                    onSaved={() => onOpenChange(false)}
                    onPendingChange={setPending}
                  />
                )}
              </QueryStateBoundary>
            </LayoutContent>
          ) : null
        }
        footer={
          open ? (
            <LayoutFooter>
              <div className="flex flex-wrap items-center justify-end gap-2">
                <Button
                  label={t("cancel")}
                  isDisabled={pending}
                  onClick={() => requestOpenChange(false)}
                />
                <Button
                  type="submit"
                  form={formId}
                  variant="primary"
                  label={t("save_changes")}
                  isLoading={pending}
                  isInterruptible
                />
              </div>
            </LayoutFooter>
          ) : null
        }
      />
    </Dialog>
  );
}
