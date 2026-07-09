import type { NextConfig } from "next";
const nextConfig: NextConfig = {
  async rewrites() {
    return {
      beforeFiles: [],
      afterFiles: [],
      fallback: [
        {
          source: "/:path*",
          destination: "https://calltoconvey.onrender.com/:path*",
        },
      ],
    };
  },
};

export default nextConfig;
