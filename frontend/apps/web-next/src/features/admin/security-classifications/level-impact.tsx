import { Banner } from "@astryxdesign/core/Banner";
import { queryOptions, useQuery } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { browserApi, type EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

type Impact = Schema<"SecurityLevelImpactPublic">;

const RESOURCES = [
  ["assistants", "security_level_impact_assistants"],
  ["apps", "security_level_impact_apps"],
  ["services", "security_level_impact_services"],
  ["knowledge_sources", "security_level_impact_knowledge_sources"]
] as const satisfies readonly (readonly [keyof Impact, string])[];

/** Without a group the level is previewed as the organisation's default. */
export function levelImpactQueryOptions(
  api: EneoClient,
  classificationId: string | null,
  userGroupId?: string
) {
  return queryOptions({
    queryKey: ["security-level-impact", classificationId, userGroupId ?? null],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/security-classifications/level-impact/", {
          params: {
            query: {
              security_classification_id: classificationId ?? undefined,
              user_group_id: userGroupId
            }
          }
        })
      ),
    // Counts change as others work: never shown from an earlier look.
    staleTime: 0,
    gcTime: 0
  });
}

/** What saving `classificationId` as a group's level, or as the default, would change. */
export function LevelImpact({
  classificationId,
  userGroupId
}: {
  /** null: the level is cleared. */
  classificationId: string | null;
  userGroupId?: string;
}) {
  const t = useTranslations();
  const impact = useQuery(levelImpactQueryOptions(browserApi, classificationId, userGroupId));

  return (
    <QueryStateBoundary query={impact} rows={2}>
      {(data) => {
        const stopped = RESOURCES.filter(([field]) => data[field] > 0);
        return (
          <div className="flex flex-col gap-2 text-sm">
            {classificationId !== null && data.completion_models === 0 ? (
              <Banner
                status="warning"
                collapsible={false}
                title={t("security_level_impact_no_model")}
              />
            ) : null}
            <p>{t("security_level_impact_users", { count: data.affected_users })}</p>
            {stopped.length > 0 ? (
              <>
                <p>{t("security_level_impact_stopped")}</p>
                <ul className="ms-5 list-disc">
                  {stopped.map(([field, key]) => (
                    <li key={field}>{t(key, { count: data[field] })}</li>
                  ))}
                </ul>
              </>
            ) : null}
          </div>
        );
      }}
    </QueryStateBoundary>
  );
}
