SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((((movie_companies CROSS JOIN (title CROSS JOIN movie_link)) CROSS JOIN company_type) CROSS JOIN cast_info) CROSS JOIN aka_name) CROSS JOIN movie_keyword) CROSS JOIN link_type) CROSS JOIN keyword) CROSS JOIN name
WHERE cast_info.nr_order = 7
  AND company_type.kind = 'special effects companies'
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id;
