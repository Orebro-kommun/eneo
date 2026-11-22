import { Text } from "@astryxdesign/core/Text";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { securityClassificationsQueryOptions } from "@/features/admin/security-classifications/security-classifications";
import type { AdminUser } from "./users";

/** The level the user works at and where it comes from; nothing while classification is off. */
export function UserSecurityLevel({ user }: { user: AdminUser }) {
  const t = useTranslations();
  const { data } = useQuery(securityClassificationsQueryOptions(browserApi));
  // Read again when the user's groups change in this dialog: the list row is a snapshot.
  const { data: current = user } = useQuery({
    queryKey: ["admin-users", "one", user.username],
    queryFn: () =>
      unwrap(
        browserApi.GET("/api/v1/admin/users/{username}/", {
          params: { path: { username: user.username } }
        })
      )
  });
  if (!data?.security_enabled) return null;

  const effective = current.effective_security_level;
  const level =
    data.security_classifications.find((item) => item.id === effective.security_classification_id)
      ?.name ?? null;
  const group =
    current.user_groups?.find((item) => item.id === effective.user_group_id)?.name ?? null;

  return (
    <div className="border-ax-border flex flex-col gap-1 border-t pt-4">
      <Text weight="medium">{t("user_security_level")}</Text>
      <Text>
        {level === null
          ? t("user_security_level_none")
          : effective.source === "group" && group !== null
            ? t("user_security_level_from_group", { level, group })
            : effective.source === "default"
              ? t("user_security_level_from_default", { level })
              : level}
      </Text>
    </div>
  );
}
