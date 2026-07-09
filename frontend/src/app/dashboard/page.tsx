import React from 'react';
import { 
  Settings2, 
  Plus, 
  Download, 
  Upload, 
  Search, 
  MoreHorizontal,
  ChevronLeft,
  ChevronRight,
  Filter
} from 'lucide-react';
import { createClient } from '@/utils/supabase/server';

export default async function Page() {
  // Initialize Supabase client (ready for actual data fetching)
  const supabase = await createClient();
  // Example data fetch (commented out until tables exist)
  // const { data: records } = await supabase.from('module_records').select('*');

  // MOCK DATA for layout purposes
  const dynamicColumns = [
    { key: 'name', label: 'Name' },
    { key: 'phone', label: 'Phone Number' },
    { key: 'email', label: 'Email' },
    { key: 'location', label: 'Location' },
    { key: 'district', label: 'District' },
    { key: 'language', label: 'Language' },
    { key: 'status', label: 'Placement Stat' }
  ];

  const records = [
    { id: 1, name: 'Alice Smith', phone: '+1 234 567 890', email: 'alice@example.com', location: 'New York', district: 'Manhattan', language: 'English', status: 'Placed' },
    { id: 2, name: 'Bob Johnson', phone: '+1 987 654 321', email: 'bob@example.com', location: 'London', district: 'Westminster', language: 'English', status: 'Pending' },
    { id: 3, name: 'Carlos Diaz', phone: '+34 600 123 456', email: 'carlos@example.com', location: 'Madrid', district: 'Centro', language: 'Spanish', status: 'Interviewing' },
    { id: 4, name: 'Diana Chen', phone: '+86 139 1234 5678', email: 'diana@example.com', location: 'Shanghai', district: 'Pudong', language: 'Mandarin', status: 'Placed' },
    { id: 5, name: 'Eva Muller', phone: '+49 151 2345 6789', email: 'eva@example.com', location: 'Berlin', district: 'Mitte', language: 'German', status: 'Pending' },
  ];

  return (
    <div className="min-h-screen bg-[#F8F9FA] text-[#111827] font-sans">
      
      {/* HEADER SECTION */}
      <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-20">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight text-gray-900">
                Manage Module: Placement Management
              </h1>
              <p className="text-sm text-gray-500 mt-1">
                Viewing and managing all dynamic records captured inside this module.
              </p>
            </div>
            
            <div className="flex items-center space-x-3">
              <button className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 shadow-sm transition-all focus:outline-none focus:ring-2 focus:ring-gray-200">
                Back
              </button>
              
              <button className="flex items-center px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 shadow-sm transition-all focus:outline-none focus:ring-2 focus:ring-gray-200">
                <Settings2 className="w-4 h-4 mr-2 text-gray-500" />
                Manage Fields
              </button>
              
              <div className="h-6 w-px bg-gray-200 mx-2"></div>
              
              <button className="flex items-center px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 shadow-sm transition-all focus:outline-none focus:ring-2 focus:ring-gray-200">
                <Upload className="w-4 h-4 mr-2 text-gray-500" />
                Import Data
              </button>
              
              <div className="relative group">
                <button className="flex items-center px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 shadow-sm transition-all focus:outline-none focus:ring-2 focus:ring-gray-200">
                  <Download className="w-4 h-4 mr-2 text-gray-500" />
                  Export
                </button>
                {/* Simple dropdown mock */}
                <div className="absolute right-0 mt-2 w-48 bg-white rounded-lg shadow-lg border border-gray-100 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 z-50">
                  <div className="py-1">
                    <a href="#" className="block px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">Export CSV</a>
                    <a href="#" className="block px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">Export Excel</a>
                  </div>
                </div>
              </div>

              <button className="flex items-center px-4 py-2 text-sm font-medium text-white bg-black border border-transparent rounded-lg hover:bg-gray-800 shadow-md hover:shadow-lg transition-all focus:outline-none focus:ring-2 focus:ring-gray-900 focus:ring-offset-2">
                <Plus className="w-4 h-4 mr-2" />
                Add Record
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* MAIN CONTENT */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        
        {/* TOOLBAR */}
        <div className="flex justify-between items-center mb-6">
          <div className="relative w-96">
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
              <Search className="h-4 w-4 text-gray-400" />
            </div>
            <input
              type="text"
              className="block w-full pl-10 pr-3 py-2 border border-gray-300 rounded-lg leading-5 bg-white placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-black focus:border-black sm:text-sm shadow-sm transition-colors"
              placeholder="Search records..."
            />
          </div>
          
          <div className="flex items-center space-x-2">
            <button className="flex items-center px-3 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 shadow-sm transition-all">
              <Filter className="w-4 h-4 mr-2 text-gray-500" />
              Filter
            </button>
          </div>
        </div>

        {/* TABLE SECTION */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">
                    <input type="checkbox" className="rounded border-gray-300 text-black focus:ring-black" />
                  </th>
                  {dynamicColumns.map((col) => (
                    <th key={col.key} scope="col" className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">
                      {col.label}
                    </th>
                  ))}
                  <th scope="col" className="relative px-6 py-4">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-100">
                {records.map((record) => (
                  <tr key={record.id} className="hover:bg-gray-50 transition-colors group cursor-pointer">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <input type="checkbox" className="rounded border-gray-300 text-black focus:ring-black" />
                    </td>
                    {dynamicColumns.map((col) => (
                      <td key={col.key} className="px-6 py-4 whitespace-nowrap text-sm text-gray-700">
                        {col.key === 'status' ? (
                          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border
                            ${record[col.key] === 'Placed' ? 'bg-gray-100 text-gray-800 border-gray-200' : 
                              record[col.key] === 'Pending' ? 'bg-white text-gray-600 border-gray-300' : 
                              'bg-gray-50 text-gray-900 border-gray-300'}`}
                          >
                            {record[col.key]}
                          </span>
                        ) : col.key === 'name' ? (
                          <span className="font-medium text-gray-900">{record[col.key]}</span>
                        ) : (
                          record[col.key as keyof typeof record]
                        )}
                      </td>
                    ))}
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      <button className="text-gray-400 hover:text-gray-900 opacity-0 group-hover:opacity-100 transition-opacity focus:outline-none">
                        <MoreHorizontal className="w-5 h-5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          
          {/* PAGINATION */}
          <div className="bg-white px-4 py-3 border-t border-gray-200 flex items-center justify-between sm:px-6">
            <div className="hidden sm:flex-1 sm:flex sm:items-center sm:justify-between">
              <div>
                <p className="text-sm text-gray-700">
                  Showing <span className="font-medium">1</span> to <span className="font-medium">5</span> of <span className="font-medium">97</span> results
                </p>
              </div>
              <div>
                <nav className="relative z-0 inline-flex rounded-md shadow-sm -space-x-px" aria-label="Pagination">
                  <a href="#" className="relative inline-flex items-center px-2 py-2 rounded-l-md border border-gray-300 bg-white text-sm font-medium text-gray-500 hover:bg-gray-50 transition-colors">
                    <span className="sr-only">Previous</span>
                    <ChevronLeft className="h-4 w-4" />
                  </a>
                  <a href="#" aria-current="page" className="z-10 bg-gray-100 border-gray-300 text-black relative inline-flex items-center px-4 py-2 border text-sm font-medium">
                    1
                  </a>
                  <a href="#" className="bg-white border-gray-300 text-gray-500 hover:bg-gray-50 relative inline-flex items-center px-4 py-2 border text-sm font-medium transition-colors">
                    2
                  </a>
                  <a href="#" className="bg-white border-gray-300 text-gray-500 hover:bg-gray-50 relative inline-flex items-center px-4 py-2 border text-sm font-medium transition-colors">
                    3
                  </a>
                  <span className="relative inline-flex items-center px-4 py-2 border border-gray-300 bg-white text-sm font-medium text-gray-700">
                    ...
                  </span>
                  <a href="#" className="bg-white border-gray-300 text-gray-500 hover:bg-gray-50 relative inline-flex items-center px-4 py-2 border text-sm font-medium transition-colors">
                    10
                  </a>
                  <a href="#" className="relative inline-flex items-center px-2 py-2 rounded-r-md border border-gray-300 bg-white text-sm font-medium text-gray-500 hover:bg-gray-50 transition-colors">
                    <span className="sr-only">Next</span>
                    <ChevronRight className="h-4 w-4" />
                  </a>
                </nav>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
