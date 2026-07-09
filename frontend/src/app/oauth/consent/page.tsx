import React from 'react';
import { ShieldCheck, AlertCircle } from 'lucide-react';

export default function OAuthConsentPage({
  searchParams,
}: {
  searchParams: { [key: string]: string | string[] | undefined };
}) {
  // In a real implementation, you would extract the consent_challenge
  // from searchParams and use the Supabase API to resolve it.
  const appName = searchParams.client_id ? "A Third-Party Application" : "An External App";

  return (
    <div className="min-h-screen bg-[#F8F9FA] flex items-center justify-center p-4">
      <div className="bg-white max-w-md w-full rounded-2xl shadow-xl border border-gray-100 p-8">
        
        <div className="flex justify-center mb-6">
          <div className="w-16 h-16 bg-gray-50 rounded-full flex items-center justify-center border border-gray-100">
            <ShieldCheck className="w-8 h-8 text-black" />
          </div>
        </div>
        
        <h1 className="text-2xl font-semibold text-center text-gray-900 mb-2">
          Authorization Request
        </h1>
        
        <p className="text-center text-gray-500 mb-6 text-sm">
          <span className="font-semibold text-black">{appName}</span> is requesting access to your ConnectFlow account.
        </p>

        <div className="bg-gray-50 rounded-xl p-4 mb-8 border border-gray-100">
          <h3 className="text-sm font-medium text-gray-900 mb-3">This application will be able to:</h3>
          <ul className="space-y-3">
            <li className="flex items-start">
              <ShieldCheck className="w-4 h-4 text-gray-400 mt-0.5 mr-2 flex-shrink-0" />
              <span className="text-sm text-gray-600">View your basic profile information (Name, Email)</span>
            </li>
            <li className="flex items-start">
              <ShieldCheck className="w-4 h-4 text-gray-400 mt-0.5 mr-2 flex-shrink-0" />
              <span className="text-sm text-gray-600">Read your dynamic records and module data</span>
            </li>
            <li className="flex items-start">
              <AlertCircle className="w-4 h-4 text-gray-400 mt-0.5 mr-2 flex-shrink-0" />
              <span className="text-sm text-gray-600">Perform actions on your behalf</span>
            </li>
          </ul>
        </div>

        <div className="flex flex-col space-y-3">
          <button className="w-full flex justify-center items-center px-4 py-3 text-sm font-medium text-white bg-black rounded-lg hover:bg-gray-800 shadow-md hover:shadow-lg transition-all focus:outline-none focus:ring-2 focus:ring-gray-900 focus:ring-offset-2">
            Authorize App
          </button>
          
          <button className="w-full flex justify-center items-center px-4 py-3 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-all focus:outline-none focus:ring-2 focus:ring-gray-200">
            Cancel
          </button>
        </div>

        <p className="text-xs text-center text-gray-400 mt-6">
          By authorizing this app, you allow it to access your data in accordance with their Terms of Service and Privacy Policy.
        </p>
      </div>
    </div>
  );
}
