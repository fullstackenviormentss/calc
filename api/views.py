import csv
from decimal import Decimal
from textwrap import dedent

from django.http import HttpResponse
from django.db.models import Avg, Max, Min, Count, Q, StdDev
from django.utils.safestring import SafeString
from markdown import markdown
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.schemas import AutoSchema
from rest_framework.compat import coreapi, coreschema

from api.pagination import ContractPagination
from api.serializers import ContractSerializer
from api.utils import get_histogram
from contracts.models import Contract, EDUCATION_CHOICES


DOCS_DESCRIPTION = dedent("""
CALC's back-end exposes a public API for its labor rates data.
This API is used by CALC's front-end Data Explorer application,
and can also be accessed by any third-party application over
the public internet.

For more developer documentation on CALC, please visit
[/docs/](/docs/).
""")

SIMPLE_QUERYARG_TYPE_MAP = {
    int: coreschema.Integer,
    str: coreschema.String,
}


def queryarg(name, _type, description):
    '''
    A simple helper method to generate a coreapi field out of a
    less verbose syntax.
    '''

    html_desc = SafeString(markdown(dedent(description)))

    return coreapi.Field(
        name,
        location="query",
        schema=SIMPLE_QUERYARG_TYPE_MAP[_type](
            description=html_desc,
        )
    )


def parse_csv_style_string(s):
    '''
    Parses comma-delimited string into an array of strings.
    Quoted sub-strings (like "engineer, junior") will be kept together to
    allow for commas in sub-strings.

    Examples:

        >>> parse_csv_style_string('jane,jim,jacky,joe')
        ['jane', 'jim', 'jacky', 'joe']

        >>> parse_csv_style_string('carrot, beet  , sunchoke')
        ['carrot', 'beet', 'sunchoke']

        >>> parse_csv_style_string('turkey, "hog, wild", cow')
        ['turkey', 'hog, wild', 'cow']
    '''
    reader = csv.reader([s], skipinitialspace=True)
    return [qq.strip() for qq in list(reader)[0] if qq.strip()]


Q_QUERYARG = queryarg("q", str, "Keywords to search by.")

GET_CONTRACTS_QUERYARGS = [
    Q_QUERYARG,
    queryarg(
        "experience_range",
        str,
        """
        Filter by a range of years of experience, e.g. `5-10`.
        This is a convenient alternative to separately
        specifying `min_experience` and `max_experience`.
        """
    ),
    queryarg(
        "min_experience",
        int,
        "Filter by minimum years of experience."
    ),
    queryarg(
        "max_experience",
        int,
        "Filter by maximum years of experience."
    ),
    queryarg(
        "min_education",
        str,
        "Filter by a minimum level of education:\n\n" + '\n'.join([
            f"* `{code}` = {desc}"
            for code, desc in EDUCATION_CHOICES
        ])
    ),
    queryarg(
        "schedule",
        str,
        """
        Filter by GSA schedule. One of the following will
        return results:

        * Environmental
        * AIMS
        * Logistics
        * Language Services
        * PES
        * MOBIS
        * Consolidated
        * IT Schedule 70
        """,
    ),
    queryarg(
        "sin",
        str,
        """
        Filter by SIN number. Examples include:

        * 899 - Environmental
        * 541 - AIMS
        * 87405 - Logistics
        * 73802 - Language Services
        * 871 - PES
        * 874 - MOBIS
        * 132 - IT Schedule 70

        Note that due to the current state of data, not all
        results may be returned.  For more details, see
        [#1033](https://github.com/18F/calc/issues/1033).
        """,
    ),
    queryarg(
        "site",
        str,
        """
        Filter by worksite. Can be `customer`, `contractor`,
        or `both`.
        """
    ),
    queryarg(
        "business_size",
        str,
        """
        Filter by business size: `s` for small business, or
        `o` for other than small business.
        """
    ),
    queryarg(
        "price",
        int,
        "Filter by exact price."
    ),
    queryarg(
        "price__gte",
        int,
        "Price must be greater than or equal to this integer."
    ),
    queryarg(
        "price__lte",
        int,
        "Price must be less than or equal to this integer."
    ),
    queryarg(
        "sort",
        str,
        "The column to sort on. Defaults to `wage_field`."
    ),
    queryarg(
        "query_type",
        str,
        """
        Defines how the user's keyword search should work.
        Can be `match_all` (default), `match_phrase`, or `match_exact`.
        """
    ),
    queryarg(
        "exclude",
        str,
        "Comma-separated list of ids to exclude from the search results."
    )
]


def get_contracts_queryset(request_params, wage_field):
    """ Filters and returns contracts based on query params

    Args:
        request_params (dict): the request query parameters, corresponding
            to GET_CONTRACTS_QUERYARGS above.
        wage_field (str): the name of the field currently being used for
            wage calculations and sorting

    Returns:
        QuerySet: a filtered and sorted QuerySet to retrieve Contract objects
    """

    query = request_params.get('q', None)
    experience_range = request_params.get('experience_range', None)
    min_experience = request_params.get('min_experience', None)
    max_experience = request_params.get('max_experience', None)
    min_education = request_params.get('min_education', None)
    education = request_params.get('education', None)
    schedule = request_params.get('schedule', None)
    sin = request_params.get('sin', None)
    site = request_params.get('site', None)
    business_size = request_params.get('business_size', None)
    price = request_params.get('price', None)
    price__gte = request_params.get('price__gte')
    price__lte = request_params.get('price__lte')
    sort = request_params.get('sort', wage_field)
    # query_type can be: [ match_all (default) | match_phrase | match_exact ]
    query_type = request_params.get('query_type', 'match_all')
    exclude = request_params.getlist('exclude')

    contracts = Contract.objects.all()

    if exclude:
        # getlist only works for key=val&key=val2, not for key=val1,val2
        exclude = exclude[0].split(',')
        contracts = contracts.exclude(id__in=exclude)

    # excludes records w/o rates for the selected contract period
    contracts = contracts.exclude(**{wage_field + '__isnull': True})

    if query:
        qs = parse_csv_style_string(query)

        if query_type not in ('match_phrase', 'match_exact'):
            contracts = contracts.multi_phrase_search(qs)
        else:
            q_objs = Q()
            for q in qs:
                if query_type == 'match_phrase':
                    q_objs.add(Q(labor_category__icontains=q), Q.OR)
                elif query_type == 'match_exact':
                    q_objs.add(Q(labor_category__iexact=q.strip()), Q.OR)
            contracts = contracts.filter(q_objs)

    if experience_range:
        years = experience_range.split(',')
        min_experience = int(years[0])
        if len(years) > 1:
            max_experience = int(years[1])

    if min_experience:
        contracts = contracts.filter(min_years_experience__gte=min_experience)

    if max_experience is not None:
        contracts = contracts.filter(min_years_experience__lte=max_experience)

    if min_education:
        for index, pair in enumerate(EDUCATION_CHOICES):
            if min_education == pair[0]:
                contracts = contracts.filter(
                    education_level__in=[
                        ed[0] for ed in EDUCATION_CHOICES[index:]
                    ]
                )

    if education:
        degrees = education.split(',')
        selected_degrees = []
        for index, pair in enumerate(EDUCATION_CHOICES):
            if pair[0] in degrees:
                selected_degrees.append(pair[0])
        contracts = contracts.filter(education_level__in=selected_degrees)

    if sin:
        contracts = contracts.filter(sin__icontains=sin)
    if schedule:
        contracts = contracts.filter(schedule__iexact=schedule)
    if site:
        contracts = contracts.filter(contractor_site__icontains=site)
    if business_size == 's':
        contracts = contracts.filter(business_size__istartswith='s')
    elif business_size == 'o':
        contracts = contracts.filter(business_size__istartswith='o')
    if price:
        contracts = contracts.filter(**{wage_field + '__exact': price})
    else:
        if price__gte:
            contracts = contracts.filter(**{wage_field + '__gte': price__gte})
        if price__lte:
            contracts = contracts.filter(**{wage_field + '__lte': price__lte})

    return contracts.order_by(*sort.split(','))


def quantize(num, precision=2):
    if num is None:
        return None
    return Decimal(num).quantize(Decimal(10) ** -precision)


class GetRates(APIView):
    """
    Get detailed information about all labor rates that match a search query.
    """

    # The AutoSchema will introspect this to ultimately generate
    # documentation about our pagination query args.
    pagination_class = ContractPagination

    schema = AutoSchema(
        manual_fields=[
            queryarg(
                "contract-year",
                int,
                """
                Return price for the given contract year (1 or 2).
                Defaults to the current year pricing.
                """
            ),
            queryarg(
                "histogram",
                int,
                """
                Number of bins to divide a wage histogram into.
                If not provided, no histogram data will be returned.
                """
            ),
        ] + GET_CONTRACTS_QUERYARGS
    )

    def get(self, request):
        bins = request.query_params.get('histogram', None)

        wage_field = self.get_wage_field(
            request.query_params.get('contract-year'))
        contracts_all = self.get_queryset(request.query_params, wage_field)

        stats = contracts_all.aggregate(
            Min(wage_field), Max(wage_field),
            Avg(wage_field), StdDev(wage_field))

        page_stats = {
            'minimum': stats[wage_field + '__min'],
            'maximum': stats[wage_field + '__max'],
            'average': quantize(stats[wage_field + '__avg']),
            'first_standard_deviation': quantize(
                stats[wage_field + '__stddev']
            )
        }

        if bins and bins.isnumeric():
            values = contracts_all.values_list(wage_field, flat=True)
            page_stats['wage_histogram'] = get_histogram(values, int(bins))

        pagination = self.pagination_class(page_stats)
        results = pagination.paginate_queryset(contracts_all, request)
        serializer = ContractSerializer(results, many=True)
        return pagination.get_paginated_response(serializer.data)

    def get_wage_field(self, year):
        wage_fields = ['current_price', 'next_year_price', 'second_year_price']
        if year in ['1', '2']:
            return wage_fields[int(year)]
        else:
            return 'current_price'

    def get_queryset(self, request, wage_field):
        return get_contracts_queryset(request, wage_field)


class GetRatesCSV(APIView):
    """
    Returns a CSV of matched records and selected search and filter options.
    """

    schema = AutoSchema(
        manual_fields=GET_CONTRACTS_QUERYARGS
    )

    def get(self, request, format=None):
        wage_field = 'current_price'
        contracts_all = get_contracts_queryset(request.GET, wage_field)

        q = request.query_params.get('q', 'None')

        # If the query starts with special chars that could be interpreted
        # as parts of a formula by Excel, then prefix the query with
        # an apostrophe so that Excel instead treats it as plain text.
        # See https://issues.apache.org/jira/browse/CSV-199
        # for more information.
        if q.startswith(('@', '-', '+', '=', '|', '%')):
            q = "'" + q

        min_education = request.query_params.get(
            'min_education', 'None Specified')
        min_experience = request.query_params.get(
            'min_experience', 'None Specified')
        site = request.query_params.get('site', 'None Specified')
        business_size = request.query_params.get(
            'business_size', 'None Specified')
        business_size_map = {
            'o': 'other than small',
            's': 'small business'
        }
        business_size_set = business_size_map.get(business_size)
        if business_size_set:
            business_size = business_size_set

        response = HttpResponse(content_type="text/csv")
        response['Content-Disposition'] = ('attachment; '
                                           'filename="pricing_results.csv"')
        writer = csv.writer(response)
        writer.writerow(("Search Query", "Minimum Education Level",
                         "Minimum Years Experience", "Worksite",
                         "Business Size", "", "", "", "", "", "", "", "", ""))
        writer.writerow((q, min_education, min_experience, site,
                         business_size, "", "", "", "", "", "", "", "", ""))
        writer.writerow(("Contract #", "Business Size", "Schedule", "Site",
                         "Begin Date", "End Date", "SIN", "Vendor Name",
                         "Labor Category", "education Level",
                         "Minimum Years Experience",
                         "Current Year Labor Price", "Next Year Labor Price",
                         "Second Year Labor Price"))

        for c in contracts_all:
            writer.writerow((c.idv_piid, c.get_readable_business_size(),
                             c.schedule, c.contractor_site, c.contract_start,
                             c.contract_end, c.sin, c.vendor_name,
                             c.labor_category, c.get_education_level_display(),
                             c.min_years_experience, c.current_price,
                             c.next_year_price, c.second_year_price))

        return response


class GetAutocomplete(APIView):
    """
    Return autocomplete suggestions for a given query.
    """

    schema = AutoSchema(
        manual_fields=[
            Q_QUERYARG,
            queryarg(
                "query_type",
                str,
                """
                Defines how the search query should work.
                Can be `match_all` (default) or `match_phrase`.
                """
            )
        ]
    )

    MAX_RESULTS = 20

    def get(self, request, format=None):
        q = request.query_params.get('q', False)
        query_type = request.query_params.get('query_type', 'match_all')

        if q:
            if query_type == 'match_phrase':
                data = Contract.objects.filter(labor_category__icontains=q)
            else:
                data = Contract.objects.multi_phrase_search(q)

            data = data.values('_normalized_labor_category').annotate(
                count=Count('_normalized_labor_category')).order_by('-count')

            # limit data to MAX_RESULTS
            data = data[:self.MAX_RESULTS]

            data = [
                {'labor_category': d['_normalized_labor_category'],
                 'count': d['count']}
                for d in data
            ]
            return Response(data)
        else:
            return Response([])
