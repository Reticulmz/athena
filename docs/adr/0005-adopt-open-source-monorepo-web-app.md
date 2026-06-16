# Adopt an open-source monorepo web app

Athena will keep its first-party Web App in the main monorepo instead of splitting it into a separate or closed-source repository. The Web App is part of the public project surface, while protection for admin and operational workflows comes from authentication, authorization, CSRF controls, audit logging, feature flags, and environment-specific configuration rather than hiding the UI source.
