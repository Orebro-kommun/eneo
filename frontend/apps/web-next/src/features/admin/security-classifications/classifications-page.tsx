import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { ArrowDownToLine, ArrowUpToLine, Lock, LockOpen, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslations } from "use-intl";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { PageHeader } from "@/components/composites/page-header";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { browserApi } from "@/lib/api/browser";
import Link from "@/lib/link";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { ClassificationDialog } from "./classification-dialog";
import { LevelImpact } from "./level-impact";
import {
  SECURITY_CLASSIFICATIONS_KEY,
  highestFirst,
  securityClassificationsQueryOptions,
  spacesBelowDefaultQueryOptions,
  type SecurityClassification
} from "./security-classifications";

function ClassificationActions({
  classification,
  isHighest,
  isLowest,
  onMove
}: {
  classification: SecurityClassification;
  isHighest: boolean;
  isLowest: boolean;
  onMove: (direction: "up" | "down") => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [showEdit, setShowEdit] = useState(false);
  const [showDelete, setShowDelete] = useState(false);

  const remove = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.DELETE("/api/v1/security-classifications/{id}/", {
          params: { path: { id: classification.id } }
        })
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: SECURITY_CLASSIFICATIONS_KEY });
      setShowDelete(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <>
      <MoreMenu
        label={t("ui_more_actions_for", { name: classification.name })}
        alignment="end"
        items={[
          {
            label: t("move_up"),
            icon: <ArrowUpToLine aria-hidden="true" />,
            isDisabled: isHighest,
            onClick: () => onMove("up")
          },
          {
            label: t("move_down"),
            icon: <ArrowDownToLine aria-hidden="true" />,
            isDisabled: isLowest,
            onClick: () => onMove("down")
          },
          {
            label: t("edit"),
            icon: <Pencil aria-hidden="true" />,
            onClick: () => setShowEdit(true)
          },
          {
            label: t("delete"),
            icon: <Trash2 aria-hidden="true" />,
            variant: "destructive",
            onClick: () => setShowDelete(true)
          }
        ]}
      />
      <ClassificationDialog
        open={showEdit}
        onOpenChange={setShowEdit}
        classification={classification}
      />
      <ConfirmDialogControlled
        open={showDelete}
        onOpenChange={setShowDelete}
        title={t("delete_security_classification")}
        description={t("confirm_delete_classification", { name: classification.name })}
        confirmLabel={remove.isPending ? t("deleting") : t("delete_classification")}
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </>
  );
}

function EnableToggle({ enabled }: { enabled: boolean }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [confirm, setConfirm] = useState<null | "enable" | "disable">(null);

  const toggle = useMutation({
    mutationFn: (next: boolean) =>
      unwrap(
        browserApi.POST("/api/v1/security-classifications/enable/", { body: { enabled: next } })
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: SECURITY_CLASSIFICATIONS_KEY });
      setConfirm(null);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <SettingsRow
      title={t("security_classification")}
      description={t("enable_security_description")}
      htmlFor="security-classification-enabled"
    >
      <Label className="flex items-center justify-between gap-2 py-1 font-normal">
        {enabled ? t("enabled") : t("disabled")}
        {/* It asks first; while the confirmed change saves it stays enabled so it
            keeps focus, and a toggle meanwhile is ignored. */}
        <Switch
          id="security-classification-enabled"
          checked={enabled}
          aria-busy={toggle.isPending || undefined}
          onCheckedChange={(next) => {
            if (!toggle.isPending) setConfirm(next ? "enable" : "disable");
          }}
        />
      </Label>
      <ConfirmDialogControlled
        open={confirm !== null}
        onOpenChange={(open) => !open && setConfirm(null)}
        title={
          confirm === "disable"
            ? t("disable_security_classifications")
            : t("enable_security_classifications")
        }
        description={
          confirm === "disable"
            ? t("disable_security_classifications_dialog_description")
            : t("enable_security_classifications_dialog_description")
        }
        confirmLabel={confirm === "disable" ? t("disable") : t("enable")}
        variant={confirm === "disable" ? "destructive" : "default"}
        pending={toggle.isPending}
        onConfirm={() => toggle.mutate(confirm === "enable")}
      />
    </SettingsRow>
  );
}

const NO_DEFAULT = "__none__";

/** The level of every user who gets none from a user group. Asks before it saves. */
function DefaultUserLevel({
  classifications,
  currentId
}: {
  classifications: SecurityClassification[];
  currentId: string | null;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  // undefined: nothing asked; null: asked to clear the default.
  const [pending, setPending] = useState<SecurityClassification | null | undefined>(undefined);

  const save = useMutation({
    mutationFn: (next: SecurityClassification | null) =>
      unwrap(
        browserApi.PUT("/api/v1/security-classifications/default-user-level/", {
          body: { security_classification: next ? { id: next.id } : null }
        })
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: SECURITY_CLASSIFICATIONS_KEY });
      setPending(undefined);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <SettingsRow title={t("default_user_level")} description={t("default_user_level_description")}>
      <Select
        value={currentId ?? NO_DEFAULT}
        onValueChange={(value) => {
          if (save.isPending || value === (currentId ?? NO_DEFAULT)) return;
          setPending(classifications.find((item) => item.id === value) ?? null);
        }}
      >
        <SelectTrigger className="w-64" aria-label={t("default_user_level")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NO_DEFAULT}>{t("no_default_user_level")}</SelectItem>
          {classifications.map((classification) => (
            <SelectItem key={classification.id} value={classification.id}>
              {classification.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <ConfirmDialogControlled
        open={pending !== undefined}
        onOpenChange={(open) => !open && setPending(undefined)}
        title={t("change_default_user_level")}
        description={
          pending
            ? t("confirm_default_user_level", { name: pending.name })
            : t("confirm_clear_default_user_level")
        }
        confirmLabel={save.isPending ? t("saving") : t("confirm")}
        variant="default"
        pending={save.isPending}
        onConfirm={() => {
          if (pending !== undefined) save.mutate(pending);
        }}
      >
        {pending !== undefined && <LevelImpact classificationId={pending?.id ?? null} />}
      </ConfirmDialogControlled>
    </SettingsRow>
  );
}

/** Existing shared spaces are never changed by a default level: the admin finds them here. */
function SpacesBelowDefault({ classifications }: { classifications: SecurityClassification[] }) {
  const t = useTranslations();
  const { data: spaces } = useQuery(spacesBelowDefaultQueryOptions(browserApi));
  if (!spaces?.length) return null;

  return (
    <SettingsRow
      title={t("spaces_below_default_level")}
      description={t("spaces_below_default_level_description")}
    >
      <ul className="flex flex-col gap-1 text-sm">
        {spaces.map((space) => (
          <li key={space.id} className="flex flex-wrap items-baseline justify-between gap-x-4">
            <Link
              href={`/spaces/${space.id}/settings?section=security`}
              className="min-w-0 break-words underline"
            >
              {space.name}
            </Link>
            <span className="text-ax-text-secondary">
              {classifications.find((item) => item.id === space.security_classification_id)?.name ??
                t("spaces_below_default_level_unclassified")}
            </span>
          </li>
        ))}
      </ul>
    </SettingsRow>
  );
}

export function SecurityClassificationsPage() {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const { data } = useSuspenseQuery(securityClassificationsQueryOptions(browserApi));
  const [showCreate, setShowCreate] = useState(false);

  const ordered = highestFirst(data.security_classifications);

  const reorder = useMutation({
    // The rank endpoint takes ids least-secure first, so reverse the display order.
    mutationFn: (displayOrder: SecurityClassification[]) =>
      unwrap(
        browserApi.PATCH("/api/v1/security-classifications/", {
          body: {
            security_classifications: [...displayOrder].reverse().map((item) => ({ id: item.id }))
          }
        })
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: SECURITY_CLASSIFICATIONS_KEY }),
    onError: (error) => toastApiError(error, t)
  });

  function move(index: number, direction: "up" | "down") {
    const target = direction === "up" ? index - 1 : index + 1;
    const current = ordered[index];
    const swap = ordered[target];
    if (!current || !swap) return;
    const next = [...ordered];
    next[index] = swap;
    next[target] = current;
    reorder.mutate(next);
  }

  return (
    <div className="flex w-full max-w-4xl flex-col gap-6">
      <PageHeader title={t("security_classifications")} />

      <SettingsGroup title={t("general")}>
        <EnableToggle enabled={data.security_enabled} />
        {data.security_enabled && (
          <DefaultUserLevel
            classifications={ordered}
            currentId={data.default_user_security_classification_id ?? null}
          />
        )}
        {data.security_enabled && data.default_user_security_classification_id && (
          <SpacesBelowDefault classifications={ordered} />
        )}
      </SettingsGroup>

      <SettingsGroup title={t("configuration")}>
        <SettingsRow title={t("classifications")} description={t("classifications_description")}>
          <div className="flex justify-end">
            <Button size="sm" onClick={() => setShowCreate(true)}>
              {t("create_security_classification")}
            </Button>
          </div>
          <div className="relative flex flex-col gap-2">
            {ordered.length > 0 && (
              <div className="text-muted-foreground flex items-center gap-2 text-sm font-medium">
                <Lock className="size-4" /> {t("highest_security")}
              </div>
            )}
            {ordered.length === 0 ? (
              <p className="text-muted-foreground py-6 text-center text-sm">
                {t("no_security_classifications")}
              </p>
            ) : (
              ordered.map((classification, index) => (
                <div
                  key={classification.id}
                  className="border-border bg-card flex items-start justify-between gap-4 rounded-lg border p-4"
                >
                  <div className="flex min-w-0 flex-col gap-1">
                    <span className="font-semibold">{classification.name}</span>
                    {classification.description && (
                      <span className="text-muted-foreground text-sm">
                        {classification.description}
                      </span>
                    )}
                  </div>
                  <ClassificationActions
                    classification={classification}
                    isHighest={index === 0}
                    isLowest={index === ordered.length - 1}
                    onMove={(direction) => move(index, direction)}
                  />
                </div>
              ))
            )}
            {ordered.length > 0 && (
              <div className="text-muted-foreground flex items-center gap-2 text-sm font-medium">
                <LockOpen className="size-4" /> {t("lowest_security")}
              </div>
            )}
          </div>
        </SettingsRow>
      </SettingsGroup>

      <ClassificationDialog open={showCreate} onOpenChange={setShowCreate} />
    </div>
  );
}
