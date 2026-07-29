# auth-implementation-patterns — detailed patterns and worked examples

## JWT Authentication

### Pattern 1: JWT Implementation

```typescript
// JWT structure: header.payload.signature
import jwt from "jsonwebtoken";
import { Request, Response, NextFunction } from "express";

interface JWTPayload {
  userId: string;
  email: string;
  role: string;
  iat: number;
  exp: number;
}

// Generate JWT
function generateTokens(userId: string, email: string, role: string) {
  const accessToken = jwt.sign(
    { userId, email, role },
    process.env.JWT_SECRET!,
    { expiresIn: "15m" }, // Short-lived
  );

  const refreshToken = jwt.sign(
    { userId },
    process.env.JWT_REFRESH_SECRET!,
    { expiresIn: "7d" }, // Long-lived
  );

  return { accessToken, refreshToken };
}

// Verify JWT
function verifyToken(token: string): JWTPayload {
  try {
    return jwt.verify(token, process.env.JWT_SECRET!) as JWTPayload;
  } catch (error) {
    if (error instanceof jwt.TokenExpiredError) {
      throw new Error("Token expired");
    }
    if (error instanceof jwt.JsonWebTokenError) {
      throw new Error("Invalid token");
    }
    throw error;
  }
}

// Middleware
function authenticate(req: Request, res: Response, next: NextFunction) {
  const authHeader = req.headers.authorization;
  if (!authHeader?.startsWith("Bearer ")) {
    return res.status(401).json({ error: "No token provided" });
  }

  const token = authHeader.substring(7);
  try {
    const payload = verifyToken(token);
    req.user = payload; // Attach user to request
    next();
  } catch (error) {
    return res.status(401).json({ error: "Invalid token" });
  }
}

// Usage
app.get("/api/profile", authenticate, (req, res) => {
  res.json({ user: req.user });
});
```

### Pattern 2: Refresh Token Flow

```typescript
interface StoredRefreshToken {
  token: string;
  userId: string;
  expiresAt: Date;
  createdAt: Date;
}

class RefreshTokenService {
  // Store refresh token in database
  async storeRefreshToken(userId: string, refreshToken: string) {
    const expiresAt = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000);
    await db.refreshTokens.create({
      token: await hash(refreshToken), // Hash before storing
      userId,
      expiresAt,
    });
  }

  // Refresh access token
  async refreshAccessToken(refreshToken: string) {
    // Verify refresh token
    let payload;
    try {
      payload = jwt.verify(refreshToken, process.env.JWT_REFRESH_SECRET!) as {
        userId: string;
      };
    } catch {
      throw new Error("Invalid refresh token");
    }

    // Check if token exists in database
    const storedToken = await db.refreshTokens.findOne({
      where: {
        token: await hash(refreshToken),
        userId: payload.userId,
        expiresAt: { $gt: new Date() },
      },
    });

    if (!storedToken) {
      throw new Error("Refresh token not found or expired");
    }

    // Get user
    const user = await db.users.findById(payload.userId);
    if (!user) {
      throw new Error("User not found");
    }

    // Generate new access token
    const accessToken = jwt.sign(
      { userId: user.id, email: user.email, role: user.role },
      process.env.JWT_SECRET!,
      { expiresIn: "15m" },
    );

    return { accessToken };
  }

  // Revoke refresh token (logout)
  async revokeRefreshToken(refreshToken: string) {
    await db.refreshTokens.deleteOne({
      token: await hash(refreshToken),
    });
  }

  // Revoke all user tokens (logout all devices)
  async revokeAllUserTokens(userId: string) {
    await db.refreshTokens.deleteMany({ userId });
  }
}

// API endpoints
app.post("/api/auth/refresh", async (req, res) => {
  const { refreshToken } = req.body;
  try {
    const { accessToken } =
      await refreshTokenService.refreshAccessToken(refreshToken);
    res.json({ accessToken });
  } catch (error) {
    res.status(401).json({ error: "Invalid refresh token" });
  }
});

app.post("/api/auth/logout", authenticate, async (req, res) => {
  const { refreshToken } = req.body;
  await refreshTokenService.revokeRefreshToken(refreshToken);
  res.json({ message: "Logged out successfully" });
});
```

## Session-Based Authentication

### Pattern 1: Express Session

```typescript
import session from "express-session";
import RedisStore from "connect-redis";
import { createClient } from "redis";

// Setup Redis for session storage
const redisClient = createClient({
  url: process.env.REDIS_URL,
});
await redisClient.connect();

app.use(
  session({
    store: new RedisStore({ client: redisClient }),
    secret: process.env.SESSION_SECRET!,
    resave: false,
    saveUninitialized: false,
    cookie: {
      secure: process.env.NODE_ENV === "production", // HTTPS only
      httpOnly: true, // No JavaScript access
      maxAge: 24 * 60 * 60 * 1000, // 24 hours
      sameSite: "strict", // CSRF protection
    },
  }),
);

// Login
app.post("/api/auth/login", async (req, res) => {
  const { email, password } = req.body;

  const user = await db.users.findOne({ email });
  if (!user || !(await verifyPassword(password, user.passwordHash))) {
    return res.status(401).json({ error: "Invalid credentials" });
  }

  // Store user in session
  req.session.userId = user.id;
  req.session.role = user.role;

  res.json({ user: { id: user.id, email: user.email, role: user.role } });
});

// Session middleware
function requireAuth(req: Request, res: Response, next: NextFunction) {
  if (!req.session.userId) {
    return res.status(401).json({ error: "Not authenticated" });
  }
  next();
}

// Protected route
app.get("/api/profile", requireAuth, async (req, res) => {
  const user = await db.users.findById(req.session.userId);
  res.json({ user });
});

// Logout
app.post("/api/auth/logout", (req, res) => {
  req.session.destroy((err) => {
    if (err) {
      return res.status(500).json({ error: "Logout failed" });
    }
    res.clearCookie("connect.sid");
    res.json({ message: "Logged out successfully" });
  });
});
```

## OAuth2 / Social Login

### Pattern 1: OAuth2 with Passport.js

```typescript
import { createHash, timingSafeEqual } from "node:crypto";
import cookieParser from "cookie-parser";
import type { NextFunction, Request, Response } from "express";
import passport from "passport";
import { Strategy as GoogleStrategy } from "passport-google-oauth20";
import { Strategy as GitHubStrategy } from "passport-github2";

const OAUTH_STATE_TTL_SECONDS = 300;
const AUTHORIZATION_CODE_TTL_SECONDS = 60;
const MILLISECONDS_PER_SECOND = 1_000;
const AUTHORIZATION_CODE_COOKIE_NAME = "__Host-oauth_code";
const PKCE_SHA256_CHALLENGE_PATTERN = /^[A-Za-z0-9_-]{43}$/;
const PKCE_VERIFIER_PATTERN = /^[A-Za-z0-9._~-]{43,128}$/;
// This cookie handoff assumes the frontend and API are same-site.
const AUTHORIZATION_CODE_COOKIE_OPTIONS = {
  httpOnly: true,
  secure: true,
  sameSite: "strict" as const,
  path: "/",
};

interface OAuthLoginState {
  codeChallenge: string;
}

interface AuthorizationGrant {
  userId: string;
  email: string;
  role: string;
  codeChallenge: string;
}

interface ExpiringSingleUseStore<T> {
  issue(value: T & { ttlSeconds: number }): Promise<string>;
  consume(token: string): Promise<T>;
}

class InvalidOAuthRequestError extends Error {}
class InvalidSingleUseTokenError extends Error {}

// Bind these ports to a shared Valkey/DB adapter during composition. issue()
// generates a cryptographically random token and stores its hash with the TTL;
// consume() atomically gets and deletes one live value, rejecting missing,
// expired, or previously consumed tokens with InvalidSingleUseTokenError.
declare const oauthStateStore: ExpiringSingleUseStore<OAuthLoginState>;
declare const authorizationCodeStore: ExpiringSingleUseStore<AuthorizationGrant>;

app.use(cookieParser());

function requireString(value: unknown, field: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new InvalidOAuthRequestError(`${field} must be a non-empty string`);
  }
  return value;
}

function requirePkceChallenge(value: unknown): string {
  const challenge = requireString(value, "code_challenge");
  if (!PKCE_SHA256_CHALLENGE_PATTERN.test(challenge)) {
    throw new InvalidOAuthRequestError(
      "code_challenge must be an S256 base64url value",
    );
  }
  return challenge;
}

function requirePkceVerifier(value: unknown): string {
  const verifier = requireString(value, "code_verifier");
  if (!PKCE_VERIFIER_PATTERN.test(verifier)) {
    throw new InvalidOAuthRequestError(
      "code_verifier must be 43-128 RFC 7636 unreserved characters",
    );
  }
  return verifier;
}

function isOAuthClientError(error: unknown): boolean {
  return (
    error instanceof InvalidOAuthRequestError ||
    error instanceof InvalidSingleUseTokenError
  );
}

async function consumeOAuthState(
  req: Request,
  res: Response,
  next: NextFunction,
) {
  try {
    res.locals.oauthState = await oauthStateStore.consume(
      requireString(req.query.state, "state"),
    );
    return next();
  } catch (error) {
    if (isOAuthClientError(error)) {
      return res.status(400).json({ error: "Invalid or expired OAuth state" });
    }
    return next(error);
  }
}

// Google OAuth
passport.use(
  new GoogleStrategy(
    {
      clientID: process.env.GOOGLE_CLIENT_ID!,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET!,
      callbackURL: "/api/auth/google/callback",
    },
    async (accessToken, refreshToken, profile, done) => {
      try {
        // Find or create user
        let user = await db.users.findOne({
          googleId: profile.id,
        });

        if (!user) {
          user = await db.users.create({
            googleId: profile.id,
            email: profile.emails?.[0]?.value,
            name: profile.displayName,
            avatar: profile.photos?.[0]?.value,
          });
        }

        return done(null, user);
      } catch (error) {
        return done(error, undefined);
      }
    },
  ),
);

// oauthStateStore and authorizationCodeStore keep single-use values server-side
// with short TTLs. The frontend creates code_verifier and sends its S256
// code_challenge when starting login.
app.get("/api/auth/google", async (req, res, next) => {
  try {
    const codeChallenge = requirePkceChallenge(req.query.code_challenge);
    const state = await oauthStateStore.issue({
      codeChallenge,
      ttlSeconds: OAUTH_STATE_TTL_SECONDS,
    });

    return passport.authenticate("google", {
      scope: ["profile", "email"],
      state,
    })(req, res, next);
  } catch (error) {
    if (error instanceof InvalidOAuthRequestError) {
      return res.status(400).json({ error: error.message });
    }
    return next(error);
  }
});

app.get(
  "/api/auth/google/callback",
  consumeOAuthState,
  passport.authenticate("google", { session: false }),
  async (req, res, next) => {
    try {
      const loginState = res.locals.oauthState as OAuthLoginState;
      const code = await authorizationCodeStore.issue({
        userId: req.user.id,
        email: req.user.email,
        role: req.user.role,
        codeChallenge: loginState.codeChallenge,
        ttlSeconds: AUTHORIZATION_CODE_TTL_SECONDS,
      });

      // Keep the code out of URLs, browser history, referrers, and access logs.
      res.cookie(AUTHORIZATION_CODE_COOKIE_NAME, code, {
        ...AUTHORIZATION_CODE_COOKIE_OPTIONS,
        maxAge: AUTHORIZATION_CODE_TTL_SECONDS * MILLISECONDS_PER_SECOND,
      });
      return res.redirect(`${process.env.FRONTEND_URL}/auth/callback`);
    } catch (error) {
      return next(error);
    }
  },
);

app.post("/api/auth/token", async (req, res, next) => {
  try {
    const code = requireString(
      req.cookies[AUTHORIZATION_CODE_COOKIE_NAME],
      "authorization code cookie",
    );
    const grant = await authorizationCodeStore.consume(code);
    res.clearCookie(
      AUTHORIZATION_CODE_COOKIE_NAME,
      AUTHORIZATION_CODE_COOKIE_OPTIONS,
    );
    const actualChallenge = createHash("sha256")
      .update(requirePkceVerifier(req.body.code_verifier))
      .digest("base64url");
    const actual = Buffer.from(actualChallenge);
    const expected = Buffer.from(grant.codeChallenge);

    if (
      actual.length !== expected.length ||
      !timingSafeEqual(actual, expected)
    ) {
      return res.status(400).json({ error: "Invalid PKCE verifier" });
    }

    // The frontend sends only code_verifier in a credentialed POST. The
    // HttpOnly authorization-code cookie is attached by the browser.
    return res.json(generateTokens(grant.userId, grant.email, grant.role));
  } catch (error) {
    if (isOAuthClientError(error)) {
      return res.status(400).json({ error: "Invalid authorization grant" });
    }
    return next(error);
  }
});
```

## Authorization Patterns

### Pattern 1: Role-Based Access Control (RBAC)

```typescript
enum Role {
  USER = "user",
  MODERATOR = "moderator",
  ADMIN = "admin",
}

const roleHierarchy: Record<Role, Role[]> = {
  [Role.ADMIN]: [Role.ADMIN, Role.MODERATOR, Role.USER],
  [Role.MODERATOR]: [Role.MODERATOR, Role.USER],
  [Role.USER]: [Role.USER],
};

function hasRole(userRole: Role, requiredRole: Role): boolean {
  return roleHierarchy[userRole].includes(requiredRole);
}

// Middleware
function requireRole(...roles: Role[]) {
  return (req: Request, res: Response, next: NextFunction) => {
    if (!req.user) {
      return res.status(401).json({ error: "Not authenticated" });
    }

    if (!roles.some((role) => hasRole(req.user.role, role))) {
      return res.status(403).json({ error: "Insufficient permissions" });
    }

    next();
  };
}

// Usage
app.delete(
  "/api/users/:id",
  authenticate,
  requireRole(Role.ADMIN),
  async (req, res) => {
    // Only admins can delete users
    await db.users.delete(req.params.id);
    res.json({ message: "User deleted" });
  },
);
```

### Pattern 2: Permission-Based Access Control

```typescript
enum Permission {
  READ_USERS = "read:users",
  WRITE_USERS = "write:users",
  DELETE_USERS = "delete:users",
  READ_POSTS = "read:posts",
  WRITE_POSTS = "write:posts",
}

const rolePermissions: Record<Role, Permission[]> = {
  [Role.USER]: [Permission.READ_POSTS, Permission.WRITE_POSTS],
  [Role.MODERATOR]: [
    Permission.READ_POSTS,
    Permission.WRITE_POSTS,
    Permission.READ_USERS,
  ],
  [Role.ADMIN]: Object.values(Permission),
};

function hasPermission(userRole: Role, permission: Permission): boolean {
  return rolePermissions[userRole]?.includes(permission) ?? false;
}

function requirePermission(...permissions: Permission[]) {
  return (req: Request, res: Response, next: NextFunction) => {
    if (!req.user) {
      return res.status(401).json({ error: "Not authenticated" });
    }

    const hasAllPermissions = permissions.every((permission) =>
      hasPermission(req.user.role, permission),
    );

    if (!hasAllPermissions) {
      return res.status(403).json({ error: "Insufficient permissions" });
    }

    next();
  };
}

// Usage
app.get(
  "/api/users",
  authenticate,
  requirePermission(Permission.READ_USERS),
  async (req, res) => {
    const users = await db.users.findAll();
    res.json({ users });
  },
);
```

### Pattern 3: Resource Ownership

```typescript
// Check if user owns resource
async function requireOwnership(
  resourceType: "post" | "comment",
  resourceIdParam: string = "id",
) {
  return async (req: Request, res: Response, next: NextFunction) => {
    if (!req.user) {
      return res.status(401).json({ error: "Not authenticated" });
    }

    const resourceId = req.params[resourceIdParam];

    // Admins can access anything
    if (req.user.role === Role.ADMIN) {
      return next();
    }

    // Check ownership
    let resource;
    if (resourceType === "post") {
      resource = await db.posts.findById(resourceId);
    } else if (resourceType === "comment") {
      resource = await db.comments.findById(resourceId);
    }

    if (!resource) {
      return res.status(404).json({ error: "Resource not found" });
    }

    if (resource.userId !== req.user.userId) {
      return res.status(403).json({ error: "Not authorized" });
    }

    next();
  };
}

// Usage
app.put(
  "/api/posts/:id",
  authenticate,
  requireOwnership("post"),
  async (req, res) => {
    // User can only update their own posts
    const post = await db.posts.update(req.params.id, req.body);
    res.json({ post });
  },
);
```

## Security Best Practices

### Pattern 1: Password Security

```typescript
import bcrypt from "bcrypt";
import { z } from "zod";

// Password validation schema
const passwordSchema = z
  .string()
  .min(12, "Password must be at least 12 characters")
  .regex(/[A-Z]/, "Password must contain uppercase letter")
  .regex(/[a-z]/, "Password must contain lowercase letter")
  .regex(/[0-9]/, "Password must contain number")
  .regex(/[^A-Za-z0-9]/, "Password must contain special character");

// Hash password
async function hashPassword(password: string): Promise<string> {
  const saltRounds = 12; // 2^12 iterations
  return bcrypt.hash(password, saltRounds);
}

// Verify password
async function verifyPassword(
  password: string,
  hash: string,
): Promise<boolean> {
  return bcrypt.compare(password, hash);
}

// Registration with password validation
app.post("/api/auth/register", async (req, res) => {
  try {
    const { email, password } = req.body;

    // Validate password
    passwordSchema.parse(password);

    // Check if user exists
    const existingUser = await db.users.findOne({ email });
    if (existingUser) {
      return res.status(400).json({ error: "Email already registered" });
    }

    // Hash password
    const passwordHash = await hashPassword(password);

    // Create user
    const user = await db.users.create({
      email,
      passwordHash,
    });

    // Generate tokens
    const tokens = generateTokens(user.id, user.email, user.role);

    res.status(201).json({
      user: { id: user.id, email: user.email },
      ...tokens,
    });
  } catch (error) {
    if (error instanceof z.ZodError) {
      return res.status(400).json({ error: error.errors[0].message });
    }
    res.status(500).json({ error: "Registration failed" });
  }
});
```

### Pattern 2: Rate Limiting

```typescript
import rateLimit from "express-rate-limit";
import RedisStore from "rate-limit-redis";

// Login rate limiter
const loginLimiter = rateLimit({
  store: new RedisStore({ client: redisClient }),
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 5, // 5 attempts
  message: "Too many login attempts, please try again later",
  standardHeaders: true,
  legacyHeaders: false,
});

// API rate limiter
const apiLimiter = rateLimit({
  windowMs: 60 * 1000, // 1 minute
  max: 100, // 100 requests per minute
  standardHeaders: true,
});

// Apply to routes
app.post("/api/auth/login", loginLimiter, async (req, res) => {
  // Login logic
});

app.use("/api/", apiLimiter);
```
