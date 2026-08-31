SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((movie_link CROSS JOIN cast_info) CROSS JOIN role_type) CROSS JOIN movie_keyword) CROSS JOIN company_type) CROSS JOIN movie_companies) CROSS JOIN title
WHERE cast_info.nr_order = 1
  AND company_type.kind = 'production companies'
  AND cast_info.movie_id = title.id
  AND cast_info.role_id = role_type.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id;
