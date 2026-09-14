import React, { useEffect, useState } from "react";
import { RevenueSummary } from "./RevenueSummary";
import { useAppContext } from "../contexts/AppContext";

// Property lists are tenant-scoped - each client only owns the properties listed under their tenant_id.
const PROPERTIES_BY_TENANT: Record<string, { id: string; name: string }[]> = {
  'tenant-a': [
    { id: 'prop-001', name: 'Beach House Alpha' },
    { id: 'prop-002', name: 'City Apartment Downtown' },
    { id: 'prop-003', name: 'Country Villa Estate' },
  ],
  'tenant-b': [
    { id: 'prop-001', name: 'Mountain Lodge Beta' },
    { id: 'prop-004', name: 'Lakeside Cottage' },
    { id: 'prop-005', name: 'Urban Loft Modern' },
  ],
};

const Dashboard: React.FC = () => {
  const { user } = useAppContext();
  const tenantId = user?.tenant_id || null;
  // Unresolved/unknown tenant gets no properties - never silently default to tenant-a.
  const properties = (tenantId && PROPERTIES_BY_TENANT[tenantId]) || [];

  const [selectedProperty, setSelectedProperty] = useState(properties[0]?.id ?? '');

  // Keep selectedProperty valid when the tenant (and therefore the property list) changes.
  useEffect(() => {
    if (!properties.some((property) => property.id === selectedProperty)) {
      setSelectedProperty(properties[0]?.id ?? '');
    }
  }, [tenantId]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="p-4 lg:p-6 min-h-full">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-2xl font-bold mb-6 text-gray-900">Property Management Dashboard</h1>

        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 lg:p-6">
          <div className="mb-6">
            <div className="flex flex-col sm:flex-row sm:justify-between sm:items-start gap-4">
              <div>
                <h2 className="text-lg lg:text-xl font-medium text-gray-900 mb-2">Revenue Overview</h2>
                <p className="text-sm lg:text-base text-gray-600">
                  Monthly performance insights for your properties
                </p>
              </div>
              
              {/* Property Selector */}
              <div className="flex flex-col sm:items-end">
                <label className="text-xs font-medium text-gray-700 mb-1">Select Property</label>
                <select
                  value={selectedProperty}
                  onChange={(e) => setSelectedProperty(e.target.value)}
                  disabled={properties.length === 0}
                  className="block w-full sm:w-auto min-w-[200px] px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500 text-sm"
                >
                  {properties.map((property) => (
                    <option key={property.id} value={property.id}>
                      {property.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          <div className="space-y-6">
            {selectedProperty ? (
              <RevenueSummary propertyId={selectedProperty} />
            ) : (
              <p className="text-sm text-gray-500">No properties available for your account.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
