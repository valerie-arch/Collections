export { default } from "next-auth/middleware";

export const config = {
  // Protect everything except: the login page, NextAuth API routes, static files.
  matcher: ["/((?!login|api/auth|_next/static|_next/image|favicon.ico).*)"],
};
